from __future__ import annotations

import hashlib
from array import array
from types import SimpleNamespace
import threading
import tempfile
import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cdmw.domain.mesh import (
    MESH_EDIT_ACTIONS,
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    MeshEditCommand,
    MeshEditSelection,
    mesh_animation_clip_from_document,
)
from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service import _add_native_editor_screen_selection_payload
from cdmw.services.mesh_service import _native_editor_edit_payload


def _quad_mesh(*, two_parts: bool = False) -> ParsedMesh:
    submesh = SubMesh(
        name="quad",
        material="mat_a",
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
    submeshes = [submesh]
    if two_parts:
        second = SubMesh(
            name="quad_b",
            material="mat_b",
            texture="b.dds",
            vertices=list(submesh.vertices),
            uvs=list(submesh.uvs),
            normals=list(submesh.normals),
            faces=list(submesh.faces),
            vertex_count=4,
            face_count=2,
        )
        submeshes.append(second)
    return ParsedMesh(path="quad.pac", format="pac", submeshes=submeshes, total_vertices=4 * len(submeshes), total_faces=2 * len(submeshes), has_uvs=True)


def _changed_vertices_as_set(result: object, submesh_index: int = 0) -> set[int]:
    changed = dict(getattr(result, "changed_vertices_by_submesh"))[submesh_index]
    if isinstance(changed, Mapping):
        descriptor = changed.get("changed_vertices_binary")
        if isinstance(descriptor, Mapping):
            from cdmw.modding.mesh_native_core import _read_i32_binary_report_payload

            count = int(descriptor.get("count", 0) or 0)
            return set(_read_i32_binary_report_payload(descriptor, expected_count=count) or ())
    return {int(value) for value in changed}  # type: ignore[union-attr]


def _large_mesh_for_native_fallback_guard() -> ParsedMesh:
    vertex_count = 10_001
    vertices = [(float(index), 0.0, 0.0) for index in range(vertex_count)]
    submesh = SubMesh(
        name="large",
        material="mat_a",
        texture="a.dds",
        vertices=vertices,
        uvs=[(0.0, 0.0)] * vertex_count,
        normals=[(0.0, 0.0, 1.0)] * vertex_count,
        faces=[(0, 1, 2)],
        vertex_count=vertex_count,
        face_count=1,
    )
    return ParsedMesh(path="large.pac", format="pac", submeshes=[submesh], total_vertices=vertex_count, total_faces=1, has_uvs=True)


def _spike_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="spike.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="spike",
                material="mat_a",
                texture="a.dds",
                vertices=[
                    (0.0, 0.0, 1.0),
                    (-1.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, -1.0, 0.0),
                    (0.0, 1.0, 0.0),
                ],
                uvs=[(0.5, 0.5), (0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 5,
                faces=[(0, 1, 3), (0, 3, 2), (0, 2, 4), (0, 4, 1)],
                vertex_count=5,
                face_count=4,
            )
        ],
        total_vertices=5,
        total_faces=4,
        has_uvs=True,
    )


def _bent_two_face_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="bent.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="bent",
                material="mat_a",
                texture="a.dds",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0),
                ],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 4,
                faces=[(0, 1, 2), (0, 1, 3)],
                vertex_count=4,
                face_count=2,
            )
        ],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )


def _malformed_face_mesh() -> ParsedMesh:
    mesh = _quad_mesh()
    submesh = mesh.submeshes[0]
    submesh.faces = [
        (0, "bad", 3),
        (0, 1, 2),
        (0, float("inf"), 2),
        (0, True, 2),
        (0, 1.9, 2),
    ]  # type: ignore[list-item]
    submesh.face_count = len(submesh.faces)
    mesh.total_faces = len(submesh.faces)
    return mesh


def _loose_edge_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose_edges",
        material="mat_a",
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
    return ParsedMesh(path="loose_edges.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=0, has_uvs=True)


def _triangle_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(path="triangle.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True)


def _duplicate_vertex_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="duplicate_vertex",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 5,
        faces=[(0, 1, 2), (1, 3, 2), (0, 4, 2)],
        vertex_count=5,
        face_count=3,
    )
    return ParsedMesh(path="duplicate_vertex.pac", format="pac", submeshes=[submesh], total_vertices=5, total_faces=3, has_uvs=True)


def _two_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (0.5, 0.0),
            (0.0, 0.5),
            (2.0, 0.0),
            (2.5, 0.0),
            (2.0, 0.5),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


def _overlapping_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="overlapping_uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="overlapping_uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


class MeshServiceEditingTests(unittest.TestCase):
    def test_native_screen_selection_payload_strips_legacy_camera_fields(self) -> None:
        payload: dict[str, object] = {}

        _add_native_editor_screen_selection_payload(
            payload,
            {
                "screen_brush": {
                    "x": 10.0,
                    "yaw_degrees": 90.0,
                    "vertical_fov_degrees": 70.0,
                    "world_view_projection": [1.0] * 16,
                },
                "screen_region": {
                    "start_x": 1.0,
                    "end_x": 2.0,
                    "camera_world": [1.0] * 16,
                    "pan": [0.0, 0.0],
                },
                "target_mode": "face",
                "selection_depth_mode": "visible",
            },
        )

        screen_brush = payload["screen_brush"]
        screen_region = payload["screen_region"]
        self.assertIsInstance(screen_brush, dict)
        self.assertIsInstance(screen_region, dict)
        self.assertEqual(10.0, screen_brush["x"])
        self.assertIn("world_view_projection", screen_brush)
        self.assertNotIn("yaw_degrees", screen_brush)
        self.assertNotIn("vertical_fov_degrees", screen_brush)
        self.assertEqual(1.0, screen_region["start_x"])
        self.assertNotIn("camera_world", screen_region)
        self.assertNotIn("pan", screen_region)
        self.assertEqual("face", payload["target_mode"])

    def test_native_edit_payload_strips_legacy_screen_camera_fields(self) -> None:
        transform = _native_editor_edit_payload(
            "transform",
            {
                "screen_drag": {
                    "start_x": 0.0,
                    "end_x": 4.0,
                    "yaw_degrees": 90.0,
                    "world_view_projection": [1.0] * 16,
                },
            },
        )
        brush = _native_editor_edit_payload(
            "brush",
            {
                "screen_brush": {
                    "x": 20.0,
                    "camera_world": [1.0] * 16,
                    "world_view_projection": [1.0] * 16,
                },
                "screen_radius": {
                    "radius_pixels": 25.0,
                    "vertical_fov_degrees": 70.0,
                    "source_submesh_world_transforms": [],
                },
            },
        )

        self.assertNotIn("yaw_degrees", transform["screen_drag"])
        self.assertIn("world_view_projection", transform["screen_drag"])
        self.assertNotIn("camera_world", brush["screen_brush"])
        self.assertIn("world_view_projection", brush["screen_brush"])
        self.assertNotIn("vertical_fov_degrees", brush["screen_radius"])
        self.assertIn("source_submesh_world_transforms", brush["screen_radius"])

    def test_native_face_binary_reader_returns_tuple_faces(self) -> None:
        from cdmw.modding.mesh_native_core import _read_face_binary_report_payload

        with tempfile.TemporaryDirectory() as tmp:
            faces_path = Path(tmp) / "faces.bin"
            faces_path.write_bytes(array("i", [0, 1, 2, 2, 3, 0]).tobytes())
            faces = _read_face_binary_report_payload(
                {"path": str(faces_path), "count": 2, "components": 3, "type": "i32"},
                expected_count=2,
                vertex_count=4,
            )

        self.assertEqual([(0, 1, 2), (2, 3, 0)], faces)
        self.assertIsInstance(faces[0], tuple)

    def test_native_binary_readers_reject_non_finite_and_out_of_bounds(self) -> None:
        from cdmw.modding.mesh_native_core import (
            _read_face_binary_report_payload,
            _read_vec2_binary_report_payload,
            _read_vec3_binary_report_payload,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vec3_path = root / "vec3.bin"
            vec2_path = root / "vec2.bin"
            faces_path = root / "faces.bin"
            vec3_path.write_bytes(array("d", [0.0, float("nan"), 1.0]).tobytes())
            vec2_path.write_bytes(array("d", [0.0, float("inf")]).tobytes())
            faces_path.write_bytes(array("i", [0, 1, 4]).tobytes())

            self.assertIsNone(_read_vec3_binary_report_payload({"path": str(vec3_path), "count": 1, "components": 3, "type": "f64"}, expected_count=1))
            self.assertIsNone(_read_vec2_binary_report_payload({"path": str(vec2_path), "count": 1, "components": 2, "type": "f64"}, expected_count=1))
            self.assertIsNone(_read_face_binary_report_payload({"path": str(faces_path), "count": 1, "components": 3, "type": "i32"}, expected_count=1, vertex_count=4))

    def test_native_binary_readers_trust_native_finite_checked_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vec3_path = root / "vec3.bin"
            vec2_path = root / "vec2.bin"
            vec3_path.write_bytes(array("d", [0.0, 1.0, 2.0]).tobytes())
            vec2_path.write_bytes(array("d", [0.0, 1.0]).tobytes())

            with patch("cdmw.modding.mesh_native_core.math.isfinite", side_effect=AssertionError("duplicate finite scan")):
                self.assertEqual(
                    [(0.0, 1.0, 2.0)],
                    mesh_native_core._read_vec3_binary_report_payload(
                        {"path": str(vec3_path), "count": 1, "components": 3, "type": "f64", "finite_checked": True},
                        expected_count=1,
                    ),
                )
                self.assertEqual(
                    [(0.0, 1.0)],
                    mesh_native_core._read_vec2_binary_report_payload(
                        {"path": str(vec2_path), "count": 1, "components": 2, "type": "f64", "finite_checked": True},
                        expected_count=1,
                    ),
                )

    def test_native_binary_writers_stream_vectors_without_json_vector_allocation(self) -> None:
        from cdmw.modding import mesh_native_core

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vec3_path = root / "vec3.bin"
            vec2_path = root / "vec2.bin"
            face_path = root / "faces.bin"
            source_face_path = root / "source_faces.bin"

            with (
                patch("cdmw.modding.mesh_native_core._vec3_json", side_effect=AssertionError("vec3 json allocation")),
                patch("cdmw.modding.mesh_native_core._vec2_json", side_effect=AssertionError("vec2 json allocation")),
            ):
                vec3_descriptor = mesh_native_core._write_vec3_binary_payload(
                    vec3_path,
                    [(1, "2", 3.5), ("bad", float("nan"), 5.0), object()],
                    fallback=7.0,
                )
                vec2_descriptor = mesh_native_core._write_vec2_binary_payload(
                    vec2_path,
                    [(1, "2"), ("bad", float("inf")), object()],
                    fallback=4.0,
                )
                face_descriptor = mesh_native_core._write_face_binary_payload(
                    face_path,
                    [(0, 1, 2), [2, "3", 0]],
                )
                source_face_descriptor, source_face_indices = mesh_native_core._write_face_binary_payload_with_source_indices(
                    source_face_path,
                    [(-1, 0, 1), (0, 1, 2), (1, 3, 2)],
                    4,
                )

            vec3_data = array("d")
            vec3_data.frombytes(vec3_path.read_bytes())
            vec2_data = array("d")
            vec2_data.frombytes(vec2_path.read_bytes())
            face_data = array("i")
            face_data.frombytes(face_path.read_bytes())
            source_face_data = array("i")
            source_face_data.frombytes(source_face_path.read_bytes())

        self.assertEqual({"path": str(vec3_path), "count": 3, "components": 3, "type": "f64"}, vec3_descriptor)
        self.assertEqual([1.0, 2.0, 3.5, 7.0, 7.0, 5.0, 7.0, 7.0, 7.0], list(vec3_data))
        self.assertEqual({"path": str(vec2_path), "count": 3, "components": 2, "type": "f64"}, vec2_descriptor)
        self.assertEqual([1.0, 2.0, 4.0, 4.0, 4.0, 4.0], list(vec2_data))
        self.assertEqual({"path": str(face_path), "count": 2, "components": 3, "type": "i32"}, face_descriptor)
        self.assertEqual([0, 1, 2, 2, 3, 0], list(face_data))
        self.assertEqual({"path": str(source_face_path), "count": 2, "components": 3, "type": "i32"}, source_face_descriptor)
        self.assertEqual([1, 2], source_face_indices)
        self.assertEqual([0, 1, 2, 1, 3, 2], list(source_face_data))

    def test_native_editor_session_report_exposes_preview_triangle_groups(self) -> None:
        from cdmw.modding import mesh_native_core

        report = {
            "edit_report": {
                "submeshes": [
                    {
                        "index": 1,
                        "source_index": 0,
                        "append_submesh": True,
                        "name": "quad duplicate",
                        "material": "routed",
                        "texture": "routed.dds",
                        "extra_attrs": {
                            "preview_native_material_overrides": {"roughness": 0.45, "metalness": 0.1},
                        },
                        "preview_triangle_group": {
                            "preview_backend": "cdmw_mesh_core",
                            "source_submesh_index": 1,
                            "source_vertex_start": 0,
                            "source_vertex_count": 3,
                            "source_face_start": 0,
                            "source_face_count": 1,
                            "positions": [0.0] * 9,
                            "normals": [0.0, 0.0, 1.0] * 3,
                            "uvs": [0.0] * 6,
                            "indices": [0, 1, 2],
                        },
                    }
                ]
            }
        }

        groups = mesh_native_core.native_mesh_editor_session_preview_triangle_groups(report)

        self.assertEqual(1, len(groups))
        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual(1, groups[0]["source_submesh_index"])
        self.assertEqual(0, groups[0]["material_source_submesh_index"])
        self.assertEqual("routed", groups[0]["material_name"])
        self.assertEqual("routed.dds", groups[0]["texture_name"])
        self.assertEqual(0.45, groups[0]["roughness"])
        self.assertEqual(0.1, groups[0]["metalness"])
        self.assertEqual(0, groups[0]["source_vertex_start"])
        self.assertEqual(3, groups[0]["source_vertex_count"])

    def test_mesh_service_result_preserves_compact_changed_range(self) -> None:
        from cdmw.services.mesh_service import _changed_vertex_indices_for_result

        changed = _changed_vertex_indices_for_result({"changed_vertex_start": 1, "changed_vertex_count": 2})

        self.assertIsInstance(changed, range)
        self.assertEqual(range(1, 3), changed)

    def test_mesh_service_result_preserves_changed_vertex_binary_descriptor(self) -> None:
        from cdmw.services.mesh_service import _changed_vertex_indices_for_result

        descriptor = {
            "changed_vertices_binary": {
                "path": "changed.bin",
                "count": 2,
                "components": 1,
                "type": "i32",
                "delete_after": True,
            }
        }

        changed = _changed_vertex_indices_for_result(descriptor)

        self.assertEqual(descriptor, changed)

    def test_mesh_service_result_preserves_large_changed_set(self) -> None:
        from cdmw.services.mesh_service import _changed_vertex_indices_for_result

        changed_set = set(range(10_001))

        changed = _changed_vertex_indices_for_result(changed_set)

        self.assertIs(changed, changed_set)

    def test_service_geometry_action_uses_native_editor_session_path(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-editor-session-service", mode="edit")
        command = MeshEditCommand(
            "delete",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"_include_preview_deltas": False},
            mode="edit",
        )
        report = {
            "status": "ok",
            "topology_changed": True,
            "submesh_count": 1,
            "affected_submesh_indices": [0],
            "submeshes": [{"index": 0, "vertex_count": 3, "face_count": 1}],
            "metrics": {"cpp_ms": 1.25, "io_serialization_ms": 0.5},
            "edit_report": {
                "operation": "delete",
                "submeshes": [{"index": 0, "vertex_count": 3, "face_count": 1, "changed_vertices": [0, 1, 2]}],
            },
        }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}) as opened,
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", side_effect=AssertionError("edit apply should inline native selection")) as selected,
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=report) as applied,
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("native mesh hydrated")),
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("native topology should clear selection without Python prune")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            result = service.apply_command(view.session_id, command)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertTrue(service._session(view.session_id).selection.is_empty())
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(1, service.session_view(view.session_id).face_count)
        opened.assert_called_once()
        selected.assert_not_called()
        applied.assert_called_once()
        self.assertEqual("delete", applied.call_args.args[1]["operation"])
        self.assertNotIn("_include_preview_deltas", applied.call_args.args[1])
        self.assertFalse(applied.call_args.kwargs["include_preview_deltas"])
        self.assertEqual(
            {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {0: {0}}},
            applied.call_args.kwargs["selection"],
        )
        self.assertEqual(1.25, result.metrics["cpp_ms"])
        self.assertEqual(0.5, result.metrics["io_serialization_ms"])
        self.assertGreaterEqual(result.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["editor_open_roundtrip_ms"], 0.0)
        self.assertEqual(0.0, result.metrics["editor_select_roundtrip_ms"])
        self.assertEqual(1.0, result.metrics["editor_select_inlined"])
        self.assertGreaterEqual(result.metrics["native_apply_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["native_apply_overhead_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["service_dispatch_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["service_total_ms"], 0.0)

    def test_service_chains_dirty_native_geometry_without_python_mesh_export(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-dirty-geometry-chain", mode="edit")
        command = MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}),
            params={"delta": (0.0, 0.0, 0.25), "_include_preview_deltas": False},
            mode="edit",
        )
        apply_count = 0

        def transform_report() -> dict[str, object]:
            nonlocal apply_count
            apply_count += 1
            return {
                "status": "ok",
                "topology_changed": False,
                "submesh_count": 1,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "metrics": {"cpp_ms": float(apply_count), "io_serialization_ms": 0.5},
                "edit_report": {
                    "operation": "transform",
                    "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2, "changed_vertices": [0, 1]}],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}) as opened,
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=lambda *_args, **_kwargs: transform_report()),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native geometry hydrated Python mesh")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            first = service.apply_command(view.session_id, command)
            second = service.apply_command(view.session_id, command)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(1.0, first.metrics["python_apply_deferred"])
        self.assertEqual(1.0, second.metrics["python_apply_deferred"])
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        opened.assert_called_once()
        self.assertEqual(2, apply_count)

    def test_service_defers_same_submesh_topology_python_apply_until_mesh_read(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-editor-session-deferred-topology", mode="edit")
        command = MeshEditCommand(
            "subdivide",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"_include_preview_deltas": False},
            mode="edit",
        )

        def sync_mesh(mesh_arg: ParsedMesh, _session_id: str, **_kwargs: object) -> bool:
            mesh_arg.submeshes[0].vertices = [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.5, 0.5, 0.0),
            ]
            mesh_arg.submeshes[0].faces = [(0, 1, 4), (1, 3, 4), (3, 2, 4), (2, 0, 4)]
            mesh_arg.submeshes[0].vertex_count = 5
            mesh_arg.submeshes[0].face_count = 4
            mesh_arg.total_vertices = 5
            mesh_arg.total_faces = 4
            return True

        report = {
            "status": "ok",
            "topology_changed": True,
            "submesh_count": 1,
            "vertex_count": 5,
            "face_count": 4,
            "affected_submesh_indices": [0],
            "submeshes": [{"index": 0, "name": "quad", "material": "mat", "texture": "a.dds", "vertex_count": 5, "face_count": 4}],
            "metrics": {"cpp_ms": 1.0, "io_serialization_ms": 0.5},
            "edit_report": {
                "operation": "subdivide",
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 5,
                        "face_count": 4,
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
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=report),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=sync_mesh) as exported,
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            result = service.apply_command(view.session_id, command)
            deferred_view = service.session_view(view.session_id)
            session = service._session(view.session_id)
            self.assertTrue(session.native_editor_mesh_dirty)
            self.assertEqual(5, deferred_view.vertex_count)
            self.assertEqual(4, deferred_view.face_count)
            synced = service.working_mesh(view.session_id)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(5, len(synced.submeshes[0].vertices))
        self.assertEqual(4, len(synced.submeshes[0].faces))
        self.assertFalse(service._session(view.session_id).native_editor_mesh_dirty)
        exported.assert_called_once()

    def test_native_dirty_topology_undo_redo_stays_resident_until_mesh_read(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-dirty-history", mode="edit")
        command = MeshEditCommand(
            "subdivide",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            mode="edit",
        )

        def topology_report(command_name: str, vertex_count: int, face_count: int) -> dict[str, object]:
            return {
                "status": "ok",
                "protocol": "mesh-editor-session-json",
                "command": command_name,
                "topology_changed": True,
                "submesh_count": 1,
                "vertex_count": vertex_count,
                "face_count": face_count,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "name": "quad", "material": "mat", "texture": "a.dds", "vertex_count": vertex_count, "face_count": face_count}],
                "metrics": {"cpp_ms": 1.0, "io_serialization_ms": 0.5},
                "edit_report": {
                    "operation": command_name,
                    "topology_changed": True,
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": vertex_count,
                            "face_count": face_count,
                            "preview_triangle_group": {
                                "preview_backend": "cdmw_mesh_core",
                                "source_submesh_index": 0,
                                "face_count": face_count,
                            },
                        }
                    ],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=topology_report("subdivide", 5, 4)),
            patch("cdmw.services.mesh_service.undo_native_mesh_editor_session", return_value=topology_report("undo", 4, 2)),
            patch("cdmw.services.mesh_service.redo_native_mesh_editor_session", return_value=topology_report("redo", 5, 4)),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native history should not export before mesh read")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            applied = service.apply_command(view.session_id, command)
            undo = service.undo(view.session_id)
            undo_view = service.session_view(view.session_id)
            redo = service.redo(view.session_id)
            redo_view = service.session_view(view.session_id)

        session = service._session(view.session_id)
        self.assertTrue(applied.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual(1.0, applied.metrics["python_apply_deferred"])
        self.assertEqual(1.0, undo.metrics["python_apply_deferred"])
        self.assertEqual(1.0, redo.metrics["python_apply_deferred"])
        self.assertEqual(4, undo_view.vertex_count)
        self.assertEqual(2, undo_view.face_count)
        self.assertEqual(5, redo_view.vertex_count)
        self.assertEqual(4, redo_view.face_count)

    def test_dirty_native_session_view_requires_native_counts(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-view-missing-counts", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ()

        with self.assertRaisesRegex(RuntimeError, "requires native submesh counts"):
            service.session_view(view.session_id)

    def test_dirty_native_undo_redo_blocks_python_history_fallback(self) -> None:
        from cdmw.services import mesh_service as mesh_service_module

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-history-fallback", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((5, 4),)
        legacy_snapshot = mesh_service_module._MeshHistorySnapshot(
            mesh=_quad_mesh(),
            mode="edit",
            selection=MeshEditSelection(),
        )
        session.undo_stack.append(legacy_snapshot)
        session.redo_stack.append(
            mesh_service_module._MeshHistorySnapshot(
                mesh=_quad_mesh(),
                mode="edit",
                selection=MeshEditSelection(),
            )
        )

        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("undo exported dirty native mesh")),
            self.assertRaisesRegex(RuntimeError, "undo requires native history"),
        ):
            service.undo(view.session_id)
        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("redo exported dirty native mesh")),
            self.assertRaisesRegex(RuntimeError, "redo requires native history"),
        ):
            service.redo(view.session_id)

    def test_native_dirty_topology_does_not_mutate_python_tangents_before_mesh_read(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].tangents = [(1.0, 0.0, 0.0)] * 4
        mesh.submeshes[0].tangent_signs = [1.0] * 4
        view = service.open_edit_session(mesh, session_id="native-editor-dirty-tangents", mode="edit")
        command = MeshEditCommand(
            "subdivide",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            mode="edit",
        )
        report = {
            "status": "ok",
            "protocol": "mesh-editor-session-json",
            "command": "apply",
            "topology_changed": True,
            "submesh_count": 1,
            "vertex_count": 5,
            "face_count": 4,
            "affected_submesh_indices": [0],
            "submeshes": [{"index": 0, "name": "quad", "material": "mat", "texture": "a.dds", "vertex_count": 5, "face_count": 4}],
            "metrics": {"cpp_ms": 1.0, "io_serialization_ms": 0.5},
            "edit_report": {
                "operation": "subdivide",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 5,
                        "face_count": 4,
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
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=report),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native topology should not export before mesh read")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            result = service.apply_command(view.session_id, command)

        session = service._session(view.session_id)
        self.assertTrue(result.ok)
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual([(1.0, 0.0, 0.0)] * 4, session.working_mesh.submeshes[0].tangents)
        self.assertEqual([1.0] * 4, session.working_mesh.submeshes[0].tangent_signs)

    def test_native_append_topology_defers_python_apply_until_mesh_read(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-dirty-append", mode="edit")
        command = MeshEditCommand(
            "duplicate",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            mode="edit",
        )
        report = {
            "status": "ok",
            "protocol": "mesh-editor-session-json",
            "command": "apply",
            "topology_changed": True,
            "submesh_count": 2,
            "vertex_count": 7,
            "face_count": 3,
            "affected_submesh_indices": [1],
            "submeshes": [
                {"index": 0, "name": "quad", "material": "mat_a", "texture": "a.dds", "vertex_count": 4, "face_count": 2},
                {"index": 1, "name": "quad duplicate", "material": "mat_a", "texture": "a.dds", "vertex_count": 3, "face_count": 1},
            ],
            "metrics": {"cpp_ms": 1.0, "io_serialization_ms": 0.5},
            "edit_report": {
                "operation": "duplicate",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 1,
                        "source_index": 0,
                        "append_submesh": True,
                        "name": "quad duplicate",
                        "material": "mat_a",
                        "texture": "a.dds",
                        "vertex_count": 3,
                        "face_count": 1,
                        "preview_triangle_group": {
                            "preview_backend": "cdmw_mesh_core",
                            "source_submesh_index": 1,
                            "source_vertex_start": 0,
                            "source_vertex_count": 3,
                            "source_face_start": 0,
                            "source_face_count": 1,
                            "positions": [0.0] * 9,
                            "normals": [0.0, 0.0, 1.0] * 3,
                            "uvs": [0.0] * 6,
                            "indices": [0, 1, 2],
                        },
                    }
                ],
            },
        }

        def sync_mesh(mesh_arg: ParsedMesh, _session_id: str, **_kwargs: object) -> bool:
            mesh_arg.submeshes.append(
                SubMesh(
                    name="quad duplicate",
                    material="mat_a",
                    texture="a.dds",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                    vertex_count=3,
                    face_count=1,
                )
            )
            mesh_arg.total_vertices = 7
            mesh_arg.total_faces = 3
            return True

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=report),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=sync_mesh) as exported,
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            result = service.apply_command(view.session_id, command)
            deferred_view = service.session_view(view.session_id)
            self.assertEqual(1, len(service._session(view.session_id).working_mesh.submeshes))
            synced = service.working_mesh(view.session_id)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertEqual((1,), result.affected_submesh_indices)
        self.assertEqual(1, result.submesh_count_delta)
        self.assertEqual(2, deferred_view.submesh_count)
        self.assertEqual(7, deferred_view.vertex_count)
        self.assertEqual(3, deferred_view.face_count)
        self.assertEqual(2, len(synced.submeshes))
        exported.assert_called_once()

    def test_service_native_editor_session_failure_blocks_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-session-fail-closed", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value=None),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("history snapshot fallback used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python mesh-edit fallback is disabled"):
                service.apply_command(view.session_id, command)

        self.assertEqual(2, service.working_mesh(view.session_id).total_faces)
        self.assertEqual(0, service.session_view(view.session_id).undo_count)

    def test_service_native_editor_session_missing_core_blocks_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-editor-session-missing-core", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("history snapshot fallback used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            with self.assertRaisesRegex(RuntimeError, "native mesh editor unavailable.*Python mesh-edit fallback is disabled"):
                service.apply_command(view.session_id, command)

        self.assertEqual(2, service.working_mesh(view.session_id).total_faces)
        self.assertEqual(0, service.session_view(view.session_id).undo_count)

    def test_service_native_editor_session_undo_redo_uses_native_history(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-editor-session-history", mode="edit")
        command = MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit")

        def native_history_report(command_name: str, vertex_count: int, face_count: int) -> dict[str, object]:
            return {
                "command": command_name,
                "topology_changed": True,
                "submesh_count": 1,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "vertex_count": vertex_count, "face_count": face_count}],
                "edit_report": {
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": vertex_count,
                            "face_count": face_count,
                            "changed_vertices": list(range(vertex_count)),
                        }
                    ]
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", return_value=native_history_report("apply", 3, 1)),
            patch("cdmw.services.mesh_service.undo_native_mesh_editor_session", return_value=native_history_report("undo", 4, 2)) as undone,
            patch("cdmw.services.mesh_service.redo_native_mesh_editor_session", return_value=native_history_report("redo", 3, 1)) as redone,
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("native mesh hydrated")),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("python/native snapshot used")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")),
        ):
            deleted = service.apply_command(view.session_id, command)
            undo = service.undo(view.session_id)
            undo_view = service.session_view(view.session_id)
            redo = service.redo(view.session_id)
            redo_view = service.session_view(view.session_id)

        self.assertTrue(deleted.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertTrue(undo.topology_changed)
        self.assertTrue(redo.topology_changed)
        self.assertEqual(1.0, deleted.metrics["python_apply_deferred"])
        self.assertEqual(1.0, undo.metrics["python_apply_deferred"])
        self.assertEqual(1.0, redo.metrics["python_apply_deferred"])
        self.assertGreaterEqual(undo.metrics["native_history_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(undo.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(undo.metrics["service_total_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["native_history_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["python_apply_ms"], 0.0)
        self.assertGreaterEqual(redo.metrics["service_total_ms"], 0.0)
        self.assertEqual(2, undo_view.face_count)
        self.assertEqual(1, redo_view.face_count)
        undone.assert_called_once()
        redone.assert_called_once()

    def test_topology_payload_compacts_nonzero_source_face_range_without_identity_list(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].faces = [(-1, 0, 1), (0, 1, 2), (1, 3, 2)]
        call_count = 0
        original = mesh_native_core._face_json_with_source_indices

        def counted_face_source_indices(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.modding.mesh_native_core._face_json_with_source_indices", side_effect=counted_face_source_indices):
                payloads = mesh_native_core._topology_edit_submeshes(
                    mesh,
                    selected_faces_by_submesh={0: {1}},
                    selected_vertices_by_submesh={},
                    binary=None,
                    sidecar_root=Path(temp_dir),
                )

        payload = payloads[0]
        self.assertEqual(1, call_count)
        self.assertEqual(1, payload["source_face_start"])
        self.assertEqual(2, payload["source_face_count"])
        self.assertNotIn("source_face_indices_binary", payload)
        self.assertEqual(0, payload["selected_face_start"])
        self.assertEqual(1, payload["selected_face_count"])
        self.assertNotIn("selected_faces_binary", payload)
        self.assertNotIn("selected_faces", payload)

    def test_load_mesh_file_parses_supported_file_without_opening_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.pam"
            mesh_path.write_bytes(b"mesh-bytes")
            parsed = _quad_mesh()
            parsed.path = ""
            parsed.format = "pam"
            service = MeshService()

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                mesh = service.load_mesh_file(mesh_path)

            parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
            self.assertIs(parsed, mesh)
            self.assertEqual(str(mesh_path), mesh.path)
            self.assertEqual(4, mesh.total_vertices)
            self.assertEqual(2, mesh.total_faces)
            self.assertEqual({}, service._sessions)

    def test_file_session_validation_exposes_mesh_asset_roundtrip_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.pac"
            mesh_path.write_bytes(b"PAR original bytes")
            parsed = _quad_mesh()
            parsed.path = ""
            service = MeshService()

            with (
                patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed),
                patch(
                    "cdmw.services.mesh_service.roundtrip_mesh_bytes",
                    return_value=SimpleNamespace(
                        report={
                            "result": "PASS",
                            "byte_identical": True,
                            "unexpected_differences": 0,
                        }
                    ),
                ) as roundtrip,
            ):
                mesh = service.load_mesh_file(mesh_path, run_roundtrip=True)
                view = service.open_edit_session(mesh, session_id="roundtrip-status", mode="edit")

            report = service.validate_export(view.session_id, available_textures=("a.dds",))

            roundtrip.assert_called_once()
            self.assertEqual("inferred", report.parse_confidence)
            self.assertEqual("PASS", report.no_op_roundtrip_status)
            self.assertIs(report.no_op_byte_identical, True)
            self.assertEqual(0, report.no_op_unexpected_differences)
            self.assertTrue(report.source_asset_hash)
            self.assertTrue(report.ok)
            self.assertIn("inferred_parse_confidence", {issue.code for issue in report.warnings})

    def test_file_session_uses_mesh_asset_bone_count_for_preserved_skinning_validation(self) -> None:
        mesh = _quad_mesh()
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (1.0,)]
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 2)
        setattr(mesh, "_cdmw_no_op_roundtrip_report", {"result": "PASS", "byte_identical": True, "unexpected_differences": 0})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="file-skinning-metadata", mode="edit")

        clean = service.validate_export(view.session_id, available_textures=("a.dds",))
        service.working_mesh(view.session_id, clone=False).submeshes[0].bone_indices[0] = (2,)
        edited = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertNotIn("missing_skeleton_metadata", {issue.code for issue in clean.blockers})
        self.assertTrue(clean.ok)
        self.assertIn("invalid_bone_index", {issue.code for issue in edited.blockers})

    def test_file_session_validation_blocks_failed_mesh_asset_roundtrip(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "FAIL", "byte_identical": False, "unexpected_differences": 1},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="roundtrip-failed", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blockers = {issue.code for issue in report.blockers}
        self.assertFalse(report.ok)
        self.assertIn("no_op_roundtrip_not_passed", blockers)
        self.assertIn("no_op_roundtrip_unexpected_differences", blockers)

    def test_file_session_validation_blocks_fallback_scan_parse_confidence(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="fallback-parse-confidence", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertFalse(report.ok)
        self.assertIn("unsafe_parse_confidence", {issue.code for issue in report.blockers})

    def test_replace_working_mesh_preserves_original_contract_and_import_operations(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (0,), (1,), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_mesh_asset_inferred_bone_count", 2)
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(mesh, "_cdmw_no_op_roundtrip_report", {"result": "PASS", "byte_identical": True, "unexpected_differences": 0})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-working-mesh", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        imported.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)
        setattr(imported, "_cdmw_imported_from_obj", True)
        setattr(imported, "_cdmw_obj_sidecar_present", True)
        setattr(
            imported,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )

        updated = service.replace_working_mesh(view.session_id, imported)
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertEqual(1, updated.revision)
        self.assertEqual(1, updated.undo_count)
        working = service.working_mesh(view.session_id, clone=False)
        self.assertEqual(b"original", getattr(working, "_cdmw_original_data"))
        self.assertEqual([(0,), (0,), (1,), (1,)], working.submeshes[0].bone_indices)
        self.assertEqual([(1.0,), (1.0,), (1.0,), (1.0,)], working.submeshes[0].bone_weights)
        self.assertEqual((0.0, 0.0, 0.0), service.base_mesh(view.session_id, clone=False).submeshes[0].vertices[0])
        self.assertTrue(report.ok)
        self.assertEqual("replace_positions_same_count", service._sessions[view.session_id].edit_operations[0]["operation"])

    def test_replace_working_mesh_preserves_selection_for_same_topology_import(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-preserve-selection", mode="edit")
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: {0, 2}},
            faces_by_submesh={0: {1}},
            source_indices={1},
        )
        service._sessions[view.session_id].selection = selection
        imported = _quad_mesh(two_parts=True)
        imported.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)

        updated = service.replace_working_mesh(view.session_id, imported)

        self.assertEqual(selection, updated.selection)
        self.assertEqual(selection, service.session_view(view.session_id).selection)
        self.assertFalse(hasattr(service.working_mesh(view.session_id, clone=False), "_cdmw_selection_diagnostics"))

    def test_replace_working_mesh_clears_selection_with_diagnostic_for_topology_change(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-clear-selection", mode="edit")
        service._sessions[view.session_id].selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: {0, 2}},
            faces_by_submesh={0: {1}},
        )
        imported = _quad_mesh()
        imported.submeshes[0].vertices.append((2.0, 2.0, 0.0))
        imported.submeshes[0].vertex_count = len(imported.submeshes[0].vertices)
        imported.total_vertices = len(imported.submeshes[0].vertices)

        updated = service.replace_working_mesh(view.session_id, imported)
        working = service.working_mesh(view.session_id, clone=False)

        self.assertTrue(updated.selection.is_empty())
        self.assertTrue(service.session_view(view.session_id).selection.is_empty())
        diagnostics = tuple(getattr(working, "_cdmw_selection_diagnostics", ()) or ())
        self.assertTrue(diagnostics)
        self.assertIn("selection_cleared_after_external_import", diagnostics[0])
        self.assertIn("topology changed", diagnostics[0])
        self.assertEqual(1, updated.undo_count)
        self.assertEqual(1, updated.revision)

    def test_replace_working_mesh_blocks_obj_sidecar_source_hash_mismatch(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_original_data", b"original")
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="replace-working-hash-mismatch", mode="edit")
        imported = _quad_mesh()
        setattr(imported, "_cdmw_imported_from_obj", True)
        setattr(imported, "_cdmw_obj_sidecar_present", True)
        setattr(imported, "_cdmw_sidecar_source_asset_hash", hashlib.sha256(b"different").hexdigest())
        setattr(imported, "_cdmw_sidecar_source_asset_size", len(b"original"))

        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            service.replace_working_mesh(view.session_id, imported)

    def test_working_mesh_native_clone_preserves_mesh_asset_lod_identity(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(
            mesh,
            "_cdmw_mesh_asset_lods",
            (
                SimpleNamespace(
                    lod_index=0,
                    name="lod0",
                    original_section_offset=62926,
                    original_section_size=18424,
                    bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
                    metadata={"source": "submeshes"},
                    submeshes=(
                        SimpleNamespace(
                            submesh_index=0,
                            stable_id="lod0_submesh0",
                            material_slot_index=0,
                            original_descriptor_offset=169,
                            original_vertex_offset=229696,
                            original_index_offset=756176,
                            original_vertex_stride=40,
                        ),
                    ),
                ),
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-clone-lod-identity", mode="edit")
        native_snapshot = {"kind": "native_submesh_snapshot", "submeshes": []}

        def restore(target: ParsedMesh, _snapshot: object) -> bool:
            target.path = mesh.path
            target.format = mesh.format
            target.submeshes = [_quad_mesh().submeshes[0]]
            return True

        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.restore_native_mesh_submesh_snapshot", side_effect=restore),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot"),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            cloned = service.working_mesh(view.session_id, clone=True)

        lods = getattr(cloned, "_cdmw_mesh_asset_lods")
        self.assertEqual(62926, lods[0].original_section_offset)
        self.assertEqual({"source": "submeshes"}, lods[0].metadata)

    def test_rebuild_report_uses_validated_session_and_original_bytes(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-report", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="abc123",
            source_size=8,
            rebuilt_size=8,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=True,
            changed_byte_ranges=(),
            output_path="out.pac",
        )

        with patch(
            "cdmw.services.mesh_service.rebuild_mesh_with_report",
            return_value=SimpleNamespace(data=b"original", report=base_report),
        ) as rebuilt:
            report = service.rebuild_report(
                view.session_id,
                available_textures=("a.dds",),
                output_path="out.pac",
            )

        rebuilt.assert_called_once()
        self.assertEqual(b"original", rebuilt.call_args.args[1])
        self.assertEqual("passed", rebuilt.call_args.kwargs["validation_status"])
        self.assertEqual("out.pac", rebuilt.call_args.kwargs["output_path"])
        self.assertEqual("abc123", report.source_asset_hash)
        self.assertEqual("out.pac", report.output_path)
        self.assertIn("missing_tangents", report.warnings)
        self.assertEqual("replace_positions_same_count", report.edit_operations[0]["operation"])

    def test_rebuild_asset_writes_validated_output_file(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-asset", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="def456",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=False,
            changed_byte_ranges=((0, 2),),
            output_path="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch(
                "cdmw.services.mesh_service.rebuild_mesh_with_report",
                return_value=SimpleNamespace(data=b"rebuilt", report=base_report),
            ) as rebuilt:
                report = service.rebuild_asset(view.session_id, target, available_textures=("a.dds",))

            self.assertEqual(b"rebuilt", target.read_bytes())

        rebuilt.assert_called_once()
        self.assertEqual(str(target), rebuilt.call_args.kwargs["output_path"])
        self.assertEqual(str(target), report.output_path)

    def test_rebuild_asset_refuses_original_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "quad.pac"
            source.write_bytes(b"original")
            mesh = _quad_mesh()
            mesh.path = str(source)
            mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
            setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
            setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
            setattr(mesh, "_cdmw_original_data", b"original")
            setattr(
                mesh,
                "_cdmw_no_op_roundtrip_report",
                {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
            )
            service = MeshService()
            view = service.open_edit_session(mesh, session_id="rebuild-asset-original", mode="edit")

            with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
                with self.assertRaisesRegex(RuntimeError, "must not overwrite"):
                    service.rebuild_asset(view.session_id, source, available_textures=("a.dds",))

        rebuilt.assert_not_called()

    def test_rebuild_report_blocks_failed_validation_before_rebuild(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-report-blocked", mode="edit")

        with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
            with self.assertRaisesRegex(RuntimeError, "mesh rebuild blocked"):
                service.rebuild_report(view.session_id, available_textures=("a.dds",))

        rebuilt.assert_not_called()

    def test_rebuild_asset_developer_override_reports_unsafe_conditions(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "fallback_scan")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-developer-override", mode="edit")
        base_report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc123",
            rebuilt_asset_hash="def456",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="fallback_scan",
            validation_status="not_run",
            byte_identical=False,
            changed_byte_ranges=((0, 1),),
            output_path="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch(
                "cdmw.services.mesh_service.rebuild_mesh_with_report",
                return_value=SimpleNamespace(data=b"rebuilt", report=base_report),
            ) as rebuilt:
                report = service.rebuild_asset(
                    view.session_id,
                    target,
                    available_textures=("a.dds",),
                    developer_override=True,
                    developer_override_reason="Forced rebuild for local testing",
                )

            self.assertEqual(b"rebuilt", target.read_bytes())

        rebuilt.assert_called_once()
        self.assertEqual("developer_override", rebuilt.call_args.kwargs["validation_status"])
        self.assertEqual("developer_override", report.validation_status)
        self.assertIn("developer_override_blocker:unsafe_parse_confidence", report.warnings)
        self.assertIn("override_reason=Forced rebuild for local testing", report.developer_overrides)
        self.assertIn("unsafe_conditions=unsafe_parse_confidence", report.developer_overrides)

    def test_rebuild_asset_developer_override_does_not_bypass_topology_blockers(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", "abc123")
        setattr(mesh, "_cdmw_original_data", b"original")
        setattr(
            mesh,
            "_cdmw_no_op_roundtrip_report",
            {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="rebuild-developer-override-blocked", mode="edit")
        service._sessions[view.session_id].working_mesh.submeshes[0].vertices.append((2.0, 2.0, 0.0))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "rebuilt.pac"
            with patch("cdmw.services.mesh_service.rebuild_mesh_with_report") as rebuilt:
                with self.assertRaisesRegex(RuntimeError, "mesh rebuild blocked"):
                    service.rebuild_asset(
                        view.session_id,
                        target,
                        available_textures=("a.dds",),
                        developer_override=True,
                        developer_override_reason="Forced rebuild for local testing",
                    )

        rebuilt.assert_not_called()

    def test_load_mesh_file_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.txt"
            mesh_path.write_text("nope", encoding="utf-8")
            service = MeshService()

            with patch("cdmw.services.mesh_service.parse_mesh") as parser:
                with self.assertRaises(ValueError):
                    service.load_mesh_file(mesh_path)

            parser.assert_not_called()

    def test_whole_part_delete_removes_submesh_rows_and_undo_restores_them(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="delete-part", mode="edit")

        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"delete_parts": True},
                mode="edit",
            ),
        )
        after_delete_names = [part.name for part in service.working_mesh(view.session_id).submeshes]
        selection_after_delete = service.session_view(view.session_id).selection.source_indices
        undo = service.undo(view.session_id)
        after_undo = service.working_mesh(view.session_id)

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(["quad_b"], after_delete_names)
        self.assertEqual((), selection_after_delete)
        self.assertTrue(undo.ok)
        self.assertEqual(["quad", "quad_b"], [part.name for part in after_undo.submeshes])

    def test_export_validator_reports_format_geometry_material_and_skinning_blockers(self) -> None:
        mesh = _malformed_face_mesh()
        submesh = mesh.submeshes[0]
        submesh.faces.append((0, 1, 99))
        submesh.uvs = submesh.uvs[:2]
        submesh.normals = []
        submesh.texture = "missing.dds"
        submesh.bone_indices = [(0, 1, 2, 3, 4)] * len(submesh.vertices)
        submesh.bone_weights = [(0.2, 0.2, 0.2, 0.2, 0.2)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-invalid", mode="edit")

        report = service.validate_export(view.session_id, available_textures=())
        blocker_codes = {issue.code for issue in report.blockers}

        self.assertFalse(report.ok)
        self.assertIn("invalid_face", blocker_codes)
        self.assertIn("invalid_face_index", blocker_codes)
        self.assertIn("uv_count_mismatch", blocker_codes)
        self.assertIn("missing_normals", blocker_codes)
        self.assertIn("missing_referenced_texture", blocker_codes)
        self.assertIn("too_many_bone_influences", blocker_codes)
        self.assertIn("missing_skeleton_metadata", blocker_codes)
        missing_skeleton = next(issue for issue in report.blockers if issue.code == "missing_skeleton_metadata")
        self.assertIn("Inferred bone count from vertex weights: 5", missing_skeleton.message)
        self.assertIn("missing_tangents", {issue.code for issue in report.warnings})

    def test_export_validator_reports_import_sidecar_warnings_after_session_clone(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_sidecar_warnings",
            (
                {
                    "code": "sidecar_material_name_changed",
                    "message": "OBJ sidecar material changed for submesh 0.",
                    "submesh_index": 0,
                    "blocks_rebuild": True,
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-sidecar-warning", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        warning = next(issue for issue in report.warnings if issue.code == "sidecar_material_name_changed")
        self.assertEqual("sidecar", warning.category)
        self.assertEqual(0, warning.submesh_index)
        blocker = next(issue for issue in report.blockers if issue.code == "sidecar_material_name_changed_blocks_rebuild")
        self.assertEqual("sidecar", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_material_and_texture_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-material-texture-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False)
        edited.submeshes[0].material = "changed_material"
        edited.submeshes[0].texture = "changed.dds"

        report = service.validate_export(view.session_id, available_textures=("changed.dds",))

        blocker_codes = {issue.code for issue in report.blockers}
        self.assertIn("material_slot_changed", blocker_codes)
        self.assertIn("texture_reference_changed", blocker_codes)

    def test_export_validator_blocks_material_slot_count_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_material_slots", ("mat_a", "mat_b"))
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-material-slot-count-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False), "_cdmw_mesh_asset_material_slots", ("mat_a",))

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "material_slot_count_changed")
        self.assertEqual("material", blocker.category)
        self.assertEqual(2, blocker.expected)
        self.assertEqual(1, blocker.actual)

    def test_export_validator_blocks_unknown_section_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_mesh_asset_unknown_sections", (("section_9", 64, 32),))
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-unknown-section-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False), "_cdmw_mesh_asset_unknown_sections", ())

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "unknown_sections_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual((("section_9", 64, 32),), blocker.expected)
        self.assertEqual((), blocker.actual)

    def test_export_validator_blocks_unknown_submesh_field_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh.submeshes[0], "unknown_fields", {"descriptor_flags": 7})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-unknown-field-changed", mode="edit")
        setattr(service.working_mesh(view.session_id, clone=False).submeshes[0], "unknown_fields", {"descriptor_flags": 8})

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "unknown_fields_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual({"descriptor_flags": 7}, blocker.expected)
        self.assertEqual({"descriptor_flags": 8}, blocker.actual)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_vertex_stride_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_stride = 40
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-vertex-stride-changed", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].source_vertex_stride = 48

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "vertex_stride_changed")
        self.assertEqual("metadata", blocker.category)
        self.assertEqual(40, blocker.expected)
        self.assertEqual(48, blocker.actual)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_source_offset_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.source_vertex_offsets = [100, 140, 180, 220]
        submesh.source_index_offset = 500
        submesh.source_index_count = 6
        submesh.source_descriptor_offset = 64
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-source-offset-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.source_vertex_offsets = []
        edited.source_index_offset = -1
        edited.source_index_count = 3
        edited.source_descriptor_offset = -1

        report = service.validate_export(view.session_id, available_textures=("a.dds",))
        blockers = {issue.code: issue for issue in report.blockers}

        self.assertEqual((100, 140, 180, 220), blockers["source_vertex_offsets_changed"].expected)
        self.assertEqual("missing", blockers["source_vertex_offsets_changed"].actual)
        self.assertEqual(500, blockers["source_index_offset_changed"].expected)
        self.assertEqual("missing", blockers["source_index_offset_changed"].actual)
        self.assertEqual(6, blockers["source_index_count_changed"].expected)
        self.assertEqual(3, blockers["source_index_count_changed"].actual)
        self.assertEqual(64, blockers["source_descriptor_offset_changed"].expected)
        self.assertEqual("missing", blockers["source_descriptor_offset_changed"].actual)

    def test_export_validator_reports_topology_count_expected_actual_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-topology-counts-changed", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.vertices.append((2.0, 2.0, 0.0))
        edited.uvs.append((1.0, 1.0))
        edited.normals.append((0.0, 0.0, 1.0))
        edited.faces.append((2, 3, 4))

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        vertex_count = next(issue for issue in report.blockers if issue.code == "submesh_vertex_count_changed")
        index_count = next(issue for issue in report.blockers if issue.code == "submesh_index_count_changed")
        self.assertEqual(4, vertex_count.expected)
        self.assertEqual(5, vertex_count.actual)
        self.assertEqual(0, vertex_count.lod_index)
        self.assertEqual(6, index_count.expected)
        self.assertEqual(9, index_count.actual)

    def test_export_validator_blocks_changed_geometry_without_source_vertex_map(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-geometry-missing-source-map", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0] = (0.25, 0.0, 0.0)

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "source_vertex_map_missing")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(4, blocker.expected)
        self.assertEqual(0, blocker.actual)
        self.assertEqual(0, blocker.lod_index)

    def test_export_validator_blocks_changed_geometry_with_invalid_source_vertex_map(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-geometry-invalid-source-map", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.vertices[0] = (0.25, 0.0, 0.0)
        edited.source_vertex_map[1] = -1

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "source_vertex_map_invalid")
        self.assertEqual("topology", blocker.category)
        self.assertEqual("non-negative source vertex ids", blocker.expected)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_lod_count_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-lod-count-changed", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        working.lod_levels = [working.submeshes, []]

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "lod_count_changed")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(1, blocker.expected)
        self.assertEqual(2, blocker.actual)
        self.assertEqual(-1, blocker.lod_index)

    def test_export_validator_blocks_lod_submesh_count_changes_against_original_session_mesh(self) -> None:
        original = _quad_mesh(two_parts=True)
        original.lod_levels = [original.submeshes, [original.submeshes[0]]]
        edited = _quad_mesh(two_parts=True)
        edited.lod_levels = [edited.submeshes, []]

        report = validate_mesh_export(edited, original_mesh=original, available_textures=("a.dds", "b.dds"))

        blocker = next(issue for issue in report.blockers if issue.code == "lod_submesh_count_changed")
        self.assertEqual("topology", blocker.category)
        self.assertEqual(1, blocker.expected)
        self.assertEqual(0, blocker.actual)
        self.assertEqual(1, blocker.lod_index)

    def test_export_validator_reports_edit_operation_blockers_after_session_clone(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "topology_replacement",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-blocker", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "blocked_edit_operation")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_same_count_operation_without_source_map(self) -> None:
        mesh = _quad_mesh()
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-source-map-blocker", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "operation_source_map_missing")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_untracked_channel_change_with_operation_list(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(
            mesh,
            "_cdmw_edit_operations",
            (
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-operation-coverage-blocker", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].uvs[0] = (0.5, 0.5)

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "untracked_edit_channel")
        self.assertEqual("operations", blocker.category)
        self.assertEqual(0, blocker.submesh_index)
        self.assertIn("uv0", blocker.message)

    def test_export_validator_requires_operations_for_imported_obj_sidecar_session(self) -> None:
        mesh = _quad_mesh()
        setattr(mesh, "_cdmw_imported_from_obj", True)
        setattr(mesh, "_cdmw_obj_sidecar_present", True)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-imported-obj-missing-operations", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        blocker = next(issue for issue in report.blockers if issue.code == "missing_edit_operations")
        self.assertEqual("operations", blocker.category)

    def test_export_validator_allows_preserved_original_unnormalized_bone_weights(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0, 1)] * len(submesh.vertices)
        submesh.bone_weights = [(0.5, 0.25)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-preserved-bone-weights", mode="edit")

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        self.assertTrue(report.ok)
        self.assertNotIn("unnormalized_bone_weights", {issue.code for issue in report.blockers})
        self.assertIn("preserved_unnormalized_bone_weights", {issue.code for issue in report.warnings})

    def test_export_validator_blocks_changed_preserved_skinning_data(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0,), (1,), (0, 1), (0,)]
        submesh.bone_weights = [(1.0,), (1.0,), (0.5, 0.5), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-skinning-data", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].bone_weights[2] = (0.25, 0.75)

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        blocker = next(issue for issue in report.blockers if issue.code == "skinning_data_changed")
        self.assertEqual("skeleton", blocker.category)
        self.assertEqual(0, blocker.submesh_index)

    def test_export_validator_blocks_changed_unnormalized_bone_weights(self) -> None:
        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0, 1)] * len(submesh.vertices)
        submesh.bone_weights = [(0.5, 0.25)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-changed-bone-weights", mode="edit")
        service.working_mesh(view.session_id, clone=False).submeshes[0].bone_weights[0] = (0.5, 0.1)

        report = service.validate_export(view.session_id, available_textures=("a.dds",), skeleton_bone_count=2)

        blockers = {issue.code for issue in report.blockers}
        self.assertFalse(report.ok)
        self.assertIn("unnormalized_bone_weights", blockers)

    def test_export_validator_blocks_pam_topology_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.format = "pam"
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-pam-topology", mode="edit")

        duplicate = service.apply_command(
            view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(duplicate.topology_changed)
        self.assertIn("unsupported_pam_topology_change", {issue.code for issue in report.blockers})
        self.assertIn("material_slot_count_mismatch", {issue.code for issue in report.warnings})

    def test_workspace_summary_reports_parts_material_routes_and_selection(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        first = mesh.submeshes[0]
        setattr(first, "cdmw_target_material_slot_index", 3)
        setattr(first, "cdmw_material_slot_kind", "base")
        setattr(first, "cdmw_source_texture_set_key", "body_set")
        first.bone_indices = [(0,), (0,), (0,), (0,)]
        first.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="workspace-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}, faces_by_submesh={0: (0,)}, source_indices=(0,)),
            ),
        )

        summary = service.workspace_summary(view.session_id)

        self.assertEqual(2, summary.part_count)
        self.assertEqual(1, summary.selected_part_count)
        self.assertEqual("quad", summary.parts[0].name)
        self.assertEqual("mat_a", summary.parts[0].material)
        self.assertEqual("a.dds", summary.parts[0].texture)
        self.assertEqual("complete", summary.parts[0].uv_coverage)
        self.assertEqual("missing", summary.parts[0].tangent_coverage)
        self.assertEqual(3, summary.parts[0].material_slot_index)
        self.assertEqual("base", summary.parts[0].material_slot_kind)
        self.assertEqual("body_set", summary.parts[0].source_texture_set_key)
        self.assertTrue(summary.parts[0].has_skinning)
        self.assertEqual(2, summary.parts[0].selected_vertex_count)
        self.assertEqual(1, summary.parts[0].selected_face_count)

    def test_workspace_summary_uses_native_session_summary_when_mesh_is_dirty(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-workspace-summary", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((5, 3),)
        native_report = {
            "command": "summary",
            "submeshes": [
                {
                    "index": 0,
                    "name": "native_quad",
                    "material": "mat_native",
                    "texture": "native.dds",
                    "vertex_count": 5,
                    "face_count": 3,
                    "uv_count": 5,
                    "normal_count": 5,
                    "tangent_count": 0,
                    "selected": True,
                    "selected_vertex_count": 2,
                    "selected_edge_count": 1,
                    "selected_face_count": 1,
                    "has_skinning": True,
                }
            ],
        }

        with (
            patch("cdmw.services.mesh_service.summarize_native_mesh_editor_session", return_value=native_report) as native_summary,
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("python selection prune")),
            patch("cdmw.services.mesh_service.summarize_mesh_workspace", side_effect=AssertionError("python workspace summary")),
        ):
            summary = service.workspace_summary(view.session_id)

        native_summary.assert_called_once_with(view.session_id)
        self.assertEqual(1, summary.part_count)
        self.assertEqual(5, summary.vertex_count)
        self.assertEqual(3, summary.face_count)
        self.assertEqual(1, summary.selected_part_count)
        self.assertEqual("native_quad", summary.parts[0].name)
        self.assertEqual("complete", summary.parts[0].uv_coverage)
        self.assertTrue(summary.parts[0].selected)
        self.assertEqual(2, summary.parts[0].selected_vertex_count)
        self.assertEqual(1, summary.parts[0].selected_edge_count)
        self.assertEqual(1, summary.parts[0].selected_face_count)
        self.assertTrue(summary.parts[0].has_skinning)

    def test_skeleton_summary_reports_skinning_rows_and_linked_metadata(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        first = mesh.submeshes[0]
        first.bone_indices = [(0,), (1,), (1, 2), (4,)]
        first.bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (0.8,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="skeleton-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        summary = service.skeleton_summary(view.session_id)
        skeleton = Skeleton(
            bones=[
                Bone(index=0, name="Root", parent_index=-1),
                Bone(index=1, name="Bip01 Head", parent_index=0),
                Bone(index=2, name="Bip01 Head_Dummy", parent_index=1),
                Bone(index=3, name="Bip01 Chest", parent_index=0),
            ],
            bone_count=4,
        )
        linked = service.attach_skeleton(
            view.session_id,
            skeleton,
            source_path="body.pab",
            skeleton_descriptor_source="body.prefabdata_xml",
            skeleton_variation_source="body.pabc",
            animation_constraint_source="body.papr",
            animation_constraint_evidence={
                "status": "read_only_constraint_string_evidence",
                "string_evidence_count": 7,
                "record_candidate_count": 2,
                "record_candidates": (
                    {
                        "offset": 48,
                        "constraint_type": "driver_expression_candidate",
                        "target_bone": "Bip01 Head:1:2",
                        "helper_bone": "Bip01 Head_Dummy",
                        "parent_bone": "P_Bip01 Chest",
                        "expression": "Local_Euler_Z*3+30.5",
                        "expression_offset": 48,
                        "target_bone_offset": 12,
                        "target_bone_delta": 36,
                        "helper_bone_offset": 20,
                        "helper_bone_delta": 28,
                        "parent_bone_offset": 28,
                        "parent_bone_delta": 20,
                        "field_confidence": "proven_readable_strings",
                        "field_offset_confidence": "proven_decoded_string_offsets",
                        "record_span_start": 12,
                        "record_span_end": 69,
                        "record_span_size": 57,
                        "record_span_field_count": 4,
                        "record_field_sequence": ("target", "helper", "parent", "expression"),
                        "record_field_sequence_confidence": "proven_decoded_string_offset_order",
                        "record_gap_status": "binary_like_interfield_gap_bytes_unbound",
                        "record_gap_classes": ("binary_gap", "binary_gap", "binary_gap"),
                        "record_gap_class_counts": {"binary_gap": 3},
                        "record_gap_count": 3,
                        "record_gap_total_size": 18,
                        "record_gap_max_size": 6,
                        "record_gap_confidence": "observed_between_decoded_string_offsets",
                        "record_gap_scalar_status": "unbound_interfield_scalar_candidates",
                        "record_gap_scalar_kind_counts": {"f32_unit_candidate": 2, "u32_u8_candidate": 1},
                        "record_gap_aligned_word_count": 6,
                        "record_gap_scalar_candidate_count": 3,
                        "record_gap_scalar_confidence": "unbound_aligned_interfield_gap_scan",
                        "record_gap_numeric_match_status": "unbound_scalar_numeric_constant_matches",
                        "record_gap_numeric_match_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                        "record_gap_numeric_match_scalar_kind_counts": {"f32_small_candidate": 1, "f32_angle_candidate": 1},
                        "record_gap_numeric_match_storage_counts": {"f32": 2},
                        "record_gap_numeric_match_pair_counts": {"target>expression": 2},
                        "record_gap_numeric_match_value_confidence_counts": {
                            "approx_float32_numeric_value_match_layout_unproven": 1,
                            "exact_float32_numeric_value_match_layout_unproven": 1,
                        },
                        "record_gap_numeric_match_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12"
                            ): 1,
                        },
                        "record_gap_numeric_match_candidate_relative_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8|rel=-16"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12|rel=-12"
                            ): 1,
                        },
                        "record_gap_numeric_match_previous_delta_counts": {"0": 1, "4": 1},
                        "record_gap_numeric_match_next_delta_counts": {"8": 1, "12": 1},
                        "record_gap_numeric_match_candidate_relative_offset_counts": {"-16": 1, "-12": 1},
                        "record_gap_numeric_match_count": 2,
                        "record_gap_numeric_match_min_previous_delta": 0,
                        "record_gap_numeric_match_max_previous_delta": 4,
                        "record_gap_numeric_match_min_next_delta": 8,
                        "record_gap_numeric_match_max_next_delta": 12,
                        "record_gap_numeric_match_min_candidate_relative_offset": -16,
                        "record_gap_numeric_match_max_candidate_relative_offset": -12,
                        "record_gap_numeric_match_offset_confidence": "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                        "record_gap_numeric_match_candidate_relative_offset_confidence": "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                        "record_gap_numeric_match_confidence": "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven",
                        "record_layout_status": "nearby_string_span_only_value_layout_unproven",
                        "expression_channels": ("Local_Euler_Z",),
                        "expression_channel_confidence": "proven",
                        "limit_operators": (),
                        "limit_operator_confidence": "unknown",
                        "expression_numeric_values": ("3", "30.5"),
                        "expression_numeric_value_confidence": "proven",
                        "expression_numeric_roles": ("channel_coefficient", "additive_offset"),
                        "expression_numeric_role_confidence": "inferred_readable_expression_syntax",
                        "expression_shape": "linear_channel_transform_candidate",
                        "expression_syntax_signature": (
                            "shape=linear_channel_transform_candidate|channels=Local_Euler_Z|"
                            "limits=none|numeric_roles=channel_coefficient>additive_offset"
                        ),
                        "expression_shape_confidence": "inferred_readable_expression_syntax",
                        "expression_shape_status": "solver_semantics_unknown",
                        "expression_semantics_confidence": "unknown",
                        "record_confidence": "inferred_nearby_string_order",
                        "solver_status": "blocked_record_layout_unproven",
                    },
                ),
                "constraint_expression_evidence": {
                    "status": "readable_expression_tokens_solver_semantics_unknown",
                    "token_confidence": "proven",
                    "semantics_confidence": "unknown",
                    "expression_role_counts": {"driver_expression": 1},
                    "shape_counts": {"linear_channel_transform_candidate": 1},
                    "channel_counts": {"Local_Euler_Z": 1},
                    "limit_operator_counts": {},
                    "numeric_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                    "syntax_signature_counts": {
                        (
                            "role=driver_expression|shape=linear_channel_transform_candidate|"
                            "channels=Local_Euler_Z|limits=none|"
                            "numeric_roles=channel_coefficient>additive_offset"
                        ): 1,
                    },
                    "numeric_value_count": 2,
                },
                "constraint_offset_evidence": {
                    "status": "readable_string_offsets_candidate_record_map",
                    "offset_confidence": "proven",
                    "record_confidence": "inferred_nearby_string_order",
                    "target_offset_count": 1,
                    "helper_offset_count": 1,
                    "parent_offset_count": 1,
                },
                "role_counts": {"bone_reference": 3, "driver_expression": 2},
                "related_physics_rows": ({"resolved_archive_path": "body.hkx"},),
                "constraint_solving_supported": False,
                "proof_gap": "record binding unknown",
            },
            socket_source="body.pab.sockets.xml",
        )

        self.assertTrue(summary.skinned)
        self.assertFalse(summary.skeleton_linked)
        self.assertEqual(1, summary.weighted_part_count)
        self.assertEqual(4, summary.weighted_vertex_count)
        self.assertEqual(5, summary.inferred_bone_count)
        self.assertEqual(1, summary.unnormalized_vertex_count)
        self.assertEqual(0, summary.invalid_row_count)
        self.assertTrue(summary.parts[0].selected)
        self.assertEqual(2, summary.parts[0].max_influences)
        self.assertEqual((0, 1, 2, 4), summary.parts[0].unique_bone_indices)
        self.assertTrue(linked.skeleton_linked)
        self.assertEqual(1, linked.invalid_row_count)
        self.assertEqual("body.pab", linked.skeleton_source)
        self.assertEqual("body.prefabdata_xml", linked.skeleton_descriptor_source)
        self.assertEqual("body.pabc", linked.skeleton_variation_source)
        self.assertEqual("linked_read_only_hash_records", linked.skeleton_variation_status)
        self.assertEqual("body.papr", linked.animation_constraint_source)
        self.assertEqual("linked_read_only_par_metadata_solver_blocked", linked.animation_constraint_status)
        self.assertEqual("read_only_constraint_string_evidence", linked.animation_constraint_evidence.status)
        self.assertEqual(7, linked.animation_constraint_evidence.string_evidence_count)
        self.assertEqual(2, linked.animation_constraint_evidence.record_candidate_count)
        self.assertEqual(1, len(linked.animation_constraint_evidence.record_candidates))
        candidate = linked.animation_constraint_evidence.record_candidates[0]
        self.assertEqual("Bip01 Head:1:2", candidate.target_bone)
        self.assertEqual(1, candidate.target_bone_index)
        self.assertEqual("suffix_base_name", candidate.target_bone_confidence)
        self.assertEqual(2, candidate.helper_bone_index)
        self.assertEqual(3, candidate.parent_bone_index)
        self.assertEqual("prefix_base_name", candidate.parent_bone_confidence)
        self.assertEqual("blocked_record_layout_unproven", candidate.solver_status)
        self.assertEqual(48, candidate.expression_offset)
        self.assertEqual(12, candidate.target_bone_offset)
        self.assertEqual(36, candidate.target_bone_delta)
        self.assertEqual(20, candidate.helper_bone_offset)
        self.assertEqual(28, candidate.helper_bone_delta)
        self.assertEqual(28, candidate.parent_bone_offset)
        self.assertEqual(20, candidate.parent_bone_delta)
        self.assertEqual("proven_readable_strings", candidate.field_confidence)
        self.assertEqual("proven_decoded_string_offsets", candidate.field_offset_confidence)
        self.assertEqual(12, candidate.record_span_start)
        self.assertEqual(69, candidate.record_span_end)
        self.assertEqual(57, candidate.record_span_size)
        self.assertEqual(4, candidate.record_span_field_count)
        self.assertEqual(("target", "helper", "parent", "expression"), candidate.record_field_sequence)
        self.assertEqual("proven_decoded_string_offset_order", candidate.record_field_sequence_confidence)
        self.assertEqual("binary_like_interfield_gap_bytes_unbound", candidate.record_gap_status)
        self.assertEqual((("binary_gap", 3),), candidate.record_gap_class_counts)
        self.assertEqual(3, candidate.record_gap_count)
        self.assertEqual(18, candidate.record_gap_total_size)
        self.assertEqual(6, candidate.record_gap_max_size)
        self.assertEqual("observed_between_decoded_string_offsets", candidate.record_gap_confidence)
        self.assertEqual("unbound_interfield_scalar_candidates", candidate.record_gap_scalar_status)
        self.assertEqual((("f32_unit_candidate", 2), ("u32_u8_candidate", 1)), candidate.record_gap_scalar_kind_counts)
        self.assertEqual(6, candidate.record_gap_aligned_word_count)
        self.assertEqual(3, candidate.record_gap_scalar_candidate_count)
        self.assertEqual("unbound_aligned_interfield_gap_scan", candidate.record_gap_scalar_confidence)
        self.assertEqual("unbound_scalar_numeric_constant_matches", candidate.record_gap_numeric_match_status)
        self.assertEqual((("additive_offset", 1), ("channel_coefficient", 1)), candidate.record_gap_numeric_match_role_counts)
        self.assertEqual((("f32_angle_candidate", 1), ("f32_small_candidate", 1)), candidate.record_gap_numeric_match_scalar_kind_counts)
        self.assertEqual((("f32", 2),), candidate.record_gap_numeric_match_storage_counts)
        self.assertEqual((("target>expression", 2),), candidate.record_gap_numeric_match_pair_counts)
        self.assertEqual(
            (
                ("approx_float32_numeric_value_match_layout_unproven", 1),
                ("exact_float32_numeric_value_match_layout_unproven", 1),
            ),
            candidate.record_gap_numeric_match_value_confidence_counts,
        )
        self.assertEqual(2, len(candidate.record_gap_numeric_match_signature_counts))
        self.assertEqual(2, len(candidate.record_gap_numeric_match_candidate_relative_signature_counts))
        self.assertEqual((("0", 1), ("4", 1)), candidate.record_gap_numeric_match_previous_delta_counts)
        self.assertEqual((("12", 1), ("8", 1)), candidate.record_gap_numeric_match_next_delta_counts)
        self.assertEqual(2, candidate.record_gap_numeric_match_count)
        self.assertEqual(0, candidate.record_gap_numeric_match_min_previous_delta)
        self.assertEqual(4, candidate.record_gap_numeric_match_max_previous_delta)
        self.assertEqual(8, candidate.record_gap_numeric_match_min_next_delta)
        self.assertEqual(12, candidate.record_gap_numeric_match_max_next_delta)
        self.assertEqual(
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
            candidate.record_gap_numeric_match_offset_confidence,
        )
        self.assertEqual(
            "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven",
            candidate.record_gap_numeric_match_confidence,
        )
        self.assertEqual("nearby_string_span_only_value_layout_unproven", candidate.record_layout_status)
        self.assertEqual(("Local_Euler_Z",), candidate.expression_channels)
        self.assertEqual("proven", candidate.expression_channel_confidence)
        self.assertEqual(("3", "30.5"), candidate.expression_numeric_values)
        self.assertEqual("proven", candidate.expression_numeric_value_confidence)
        self.assertEqual(("channel_coefficient", "additive_offset"), candidate.expression_numeric_roles)
        self.assertEqual("inferred_readable_expression_syntax", candidate.expression_numeric_role_confidence)
        self.assertEqual("linear_channel_transform_candidate", candidate.expression_shape)
        self.assertEqual(
            "shape=linear_channel_transform_candidate|channels=Local_Euler_Z|"
            "limits=none|numeric_roles=channel_coefficient>additive_offset",
            candidate.expression_syntax_signature,
        )
        self.assertEqual("inferred_readable_expression_syntax", candidate.expression_shape_confidence)
        self.assertEqual("solver_semantics_unknown", candidate.expression_shape_status)
        self.assertEqual("unknown", candidate.expression_semantics_confidence)
        self.assertIn(("target_suffix_base_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertIn(("helper_exact_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertIn(("parent_prefix_base_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertEqual(1, linked.animation_constraint_evidence.bone_match_candidate_count)
        self.assertIn(("driver_expression_candidate", 1), linked.animation_constraint_evidence.candidate_family_counts)
        self.assertIn(
            (
                "driver_expression_candidate",
                "solver_blocked_until_record_layout_and_expression_semantics_proven",
                (
                    ("candidates", 1),
                    ("solver ready", 0),
                    ("target bound", 1),
                    ("helper bound", 1),
                    ("parent bound", 1),
                    ("record layout unproven", 1),
                    ("expression semantics unknown", 1),
                ),
            ),
            linked.animation_constraint_evidence.family_readiness_rows,
        )
        self.assertEqual("readable_expression_tokens_solver_semantics_unknown", linked.animation_constraint_evidence.expression_status)
        self.assertIn(("channel Local_Euler_Z", 1), linked.animation_constraint_evidence.expression_counts)
        self.assertEqual(1, len(linked.animation_constraint_evidence.expression_syntax_signature_counts))
        self.assertEqual(2, linked.animation_constraint_evidence.expression_numeric_value_count)
        self.assertEqual("readable_string_offsets_candidate_record_map", linked.animation_constraint_evidence.field_offset_status)
        self.assertIn(("target", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertIn(("helper", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertIn(("parent", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertEqual(2, linked.animation_constraint_evidence.numeric_match_count)
        self.assertIn(("unbound_scalar_numeric_constant_matches", 1), linked.animation_constraint_evidence.numeric_match_status_counts)
        self.assertIn(("channel_coefficient", 1), linked.animation_constraint_evidence.numeric_match_role_counts)
        self.assertIn(("additive_offset", 1), linked.animation_constraint_evidence.numeric_match_role_counts)
        self.assertIn(("f32", 2), linked.animation_constraint_evidence.numeric_match_storage_counts)
        self.assertIn(("target>expression", 2), linked.animation_constraint_evidence.numeric_match_pair_counts)
        self.assertIn(
            ("approx_float32_numeric_value_match_layout_unproven", 1),
            linked.animation_constraint_evidence.numeric_match_value_confidence_counts,
        )
        self.assertIn(
            ("exact_float32_numeric_value_match_layout_unproven", 1),
            linked.animation_constraint_evidence.numeric_match_value_confidence_counts,
        )
        self.assertIn(("driver_expression_candidate", 2), linked.animation_constraint_evidence.numeric_match_family_counts)
        self.assertIn(("driver_expression_candidate", 1), linked.animation_constraint_evidence.numeric_match_family_row_counts)
        self.assertIn(
            (
                "driver_expression_candidate",
                (("additive_offset", 1), ("channel_coefficient", 1)),
            ),
            linked.animation_constraint_evidence.numeric_match_family_role_counts,
        )
        self.assertIn(
            (
                "driver_expression_candidate",
                (("target>expression", 2),),
            ),
            linked.animation_constraint_evidence.numeric_match_family_pair_counts,
        )
        self.assertIn(
            (
                "driver_expression_candidate",
                (
                    ("approx_float32_numeric_value_match_layout_unproven", 1),
                    ("exact_float32_numeric_value_match_layout_unproven", 1),
                ),
            ),
            linked.animation_constraint_evidence.numeric_match_family_value_confidence_counts,
        )
        self.assertEqual(2, len(linked.animation_constraint_evidence.numeric_match_signature_counts))
        self.assertEqual(2, len(linked.animation_constraint_evidence.numeric_match_candidate_relative_signature_counts))
        self.assertIn(("0", 1), linked.animation_constraint_evidence.numeric_match_previous_delta_counts)
        self.assertIn(("4", 1), linked.animation_constraint_evidence.numeric_match_previous_delta_counts)
        self.assertIn(("8", 1), linked.animation_constraint_evidence.numeric_match_next_delta_counts)
        self.assertIn(("12", 1), linked.animation_constraint_evidence.numeric_match_next_delta_counts)
        self.assertIn(("-16", 1), candidate.record_gap_numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-12", 1), candidate.record_gap_numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-16", 1), linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-12", 1), linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_counts)
        self.assertEqual(0, linked.animation_constraint_evidence.numeric_match_min_previous_delta)
        self.assertEqual(4, linked.animation_constraint_evidence.numeric_match_max_previous_delta)
        self.assertEqual(8, linked.animation_constraint_evidence.numeric_match_min_next_delta)
        self.assertEqual(12, linked.animation_constraint_evidence.numeric_match_max_next_delta)
        self.assertEqual(-16, candidate.record_gap_numeric_match_min_candidate_relative_offset)
        self.assertEqual(-12, candidate.record_gap_numeric_match_max_candidate_relative_offset)
        self.assertEqual(-16, linked.animation_constraint_evidence.numeric_match_min_candidate_relative_offset)
        self.assertEqual(-12, linked.animation_constraint_evidence.numeric_match_max_candidate_relative_offset)
        self.assertEqual(
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
            linked.animation_constraint_evidence.numeric_match_offset_confidence,
        )
        self.assertEqual(
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
            candidate.record_gap_numeric_match_candidate_relative_offset_confidence,
        )
        self.assertEqual(
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
            linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_confidence,
        )
        self.assertEqual(
            "solver_blocked_until_record_layout_and_expression_semantics_proven",
            linked.animation_constraint_evidence.solver_readiness_status,
        )
        self.assertIn(("solver ready", 0), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("target bound", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("record layout unproven", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("expression semantics unknown", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertEqual(1, linked.animation_constraint_evidence.related_physics_count)
        self.assertIn(("bone_reference", 3), linked.animation_constraint_evidence.role_counts)
        self.assertFalse(linked.animation_constraint_evidence.solver_supported)
        self.assertEqual("body.pab.sockets.xml", linked.socket_source)
        self.assertEqual("constraint_metadata_only", linked.animation_status)
        self.assertFalse(linked.animation_playback_ready)
        self.assertTrue(any("bone-track binding" in blocker for blocker in linked.animation_blockers))
        authoring = {row.feature: row for row in linked.authoring_status_rows}
        self.assertEqual("preview-only", authoring["Pose preview"].state)
        self.assertEqual("blocked", authoring["Weight edits"].state)
        self.assertEqual("blocked", authoring["PAPR constraints"].state)
        self.assertEqual("blocked", authoring["Archive mutation"].state)

    def test_attach_skeleton_reports_hierarchy_and_satisfies_export_metadata(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (1.0,)]
        mesh.has_bones = True
        skeleton = Skeleton(
            path="character/model/body.pab",
            bones=[
                Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                Bone(index=1, name="Spine", parent_index=0, position=(0.0, 1.0, 0.0)),
            ],
            bone_count=2,
            parser_mode="fixed",
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="attached-skeleton", mode="edit")

        summary = service.attach_skeleton(view.session_id, skeleton)
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(summary.skeleton_linked)
        self.assertEqual(2, summary.skeleton_bone_count)
        self.assertEqual(1, summary.root_bone_count)
        self.assertEqual(1, summary.max_depth)
        self.assertEqual("Root", summary.bones[1].parent_name)
        self.assertEqual("fixed", summary.skeleton_parser_mode)
        self.assertNotIn("missing_skeleton_metadata", {issue.code for issue in report.blockers})

        selected = service.select_bone(view.session_id, 1)
        enabled = service.set_pose_preview(view.session_id, True)
        rotated = service.rotate_selected_bone(view.session_id, (10.0, -5.0, "2.5"))
        reset = service.reset_pose(view.session_id)

        self.assertEqual(1, selected.pose.selected_bone_index)
        self.assertEqual("Spine", selected.pose.selected_bone_name)
        self.assertTrue(enabled.pose.enabled)
        self.assertEqual((10.0, -5.0, 2.5), rotated.pose.rotation_degrees)
        self.assertEqual(1, rotated.pose.posed_bone_count)
        self.assertEqual((0.0, 0.0, 0.0), reset.pose.rotation_degrees)
        self.assertEqual(0, reset.pose.posed_bone_count)

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )
        service.select_bone(view.session_id, 1)
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices[2] = ()
        working.submeshes[0].bone_weights[2] = ()
        transferred = service.transfer_selected_vertex_weights_from_source(view.session_id)
        self.assertEqual((0, 1), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.6, 0.4), working.submeshes[0].bone_weights[2])
        self.assertAlmostEqual(0.4, transferred.selected_vertex_weights[0].selected_bone_weight)

        weighted = service.adjust_selected_vertex_bone_weight(view.session_id, 0.2)

        self.assertEqual(1, len(weighted.selected_vertex_weights))
        self.assertAlmostEqual(0.6, weighted.selected_vertex_weights[0].selected_bone_weight)
        self.assertEqual((0, 1), service.working_mesh(view.session_id).submeshes[0].bone_indices[2])
        self.assertAlmostEqual(0.4, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][0])
        self.assertAlmostEqual(0.6, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][1])
        self.assertEqual(2, service.session_view(view.session_id).undo_count)

    def test_pose_preview_mesh_applies_skinned_bone_rotation_without_mutating_working_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="pose-preview", mode="edit")
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        service.attach_skeleton(view.session_id, skeleton)
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))

        preview = service.pose_preview_mesh(view.session_id)

        self.assertAlmostEqual(0.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(1.0, preview.submeshes[0].vertices[1][1], places=6)
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_pose_preview_mesh_uses_native_deformer_before_python_skin_loop(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="pose-preview-native-deform", mode="edit")
        service.attach_skeleton(view.session_id, Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1))
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))
        native_vertices = {
            0: (
                (0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (-1.0, 0.0, 0.0),
                (-1.0, 1.0, 0.0),
            )
        }

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_pose_preview", return_value=native_vertices) as native_pose,
            patch("cdmw.services.mesh_service.apply_native_mesh_recalculate_normals", return_value={0}),
            patch("cdmw.services.mesh_service.mesh_pose_deformed_vertices", side_effect=AssertionError("python pose skinning loop reached")),
        ):
            preview = service.pose_preview_mesh(view.session_id)

        native_pose.assert_called_once()
        self.assertAlmostEqual(0.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(1.0, preview.submeshes[0].vertices[1][1], places=6)
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_native_pose_preview_bridge_reads_binary_vertices(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        skeleton = Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1)

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("pose-preview-json", command)
            self.assertEqual(1, len(payload["bones"]))  # type: ignore[index]
            self.assertEqual(1, len(payload["rotations"]))  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertNotIn("vertices_binary", submesh_payload)
            vertices_path = Path(str(submesh_payload["vertices_output_path"]))
            vertices_path.write_bytes(
                array(
                    "d",
                    (
                        0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0,
                        -1.0, 0.0, 0.0,
                        -1.0, 1.0, 0.0,
                    ),
                ).tobytes()
            )
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "pose_preview",
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 4,
                        "changed_count": 3,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 3,
                        "vertices_binary": {"path": str(vertices_path), "count": 4, "components": 3, "type": "f64"},
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            deformed = mesh_native_core.apply_native_mesh_pose_preview(
                mesh,
                skeleton,
                {0: (0.0, 0.0, 90.0)},
            )

        self.assertIsNotNone(deformed)
        assert deformed is not None
        self.assertAlmostEqual(1.0, deformed[0][1][1], places=6)
        self.assertAlmostEqual(-1.0, deformed[0][2][0], places=6)

    def test_native_pose_preview_geometry_bridge_feeds_pose_sidecar_to_preview_geometry(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        skeleton = Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1)
        commands: list[str] = []

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            commands.append(command)
            if command == "pose-preview-json":
                submesh_payload = payload["submeshes"][0]  # type: ignore[index]
                self.assertEqual("session-0", submesh_payload["session_id"])
                vertices_path = Path(str(submesh_payload["vertices_output_path"]))
                vertices_path.write_bytes(
                    array(
                        "d",
                        (
                            0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0,
                            -1.0, 0.0, 0.0,
                            -1.0, 1.0, 0.0,
                        ),
                    ).tobytes()
                )
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "pose_preview",
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": 4,
                            "changed_count": 3,
                            "changed_vertex_start": 1,
                            "changed_vertex_count": 3,
                            "vertices_binary": {"path": str(vertices_path), "count": 4, "components": 3, "type": "f64"},
                        }
                    ],
                }
            self.assertEqual("preview-geometry-json", command)
            preview_mesh = payload["meshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", preview_mesh["session_id"])
            self.assertIn("positions_binary", preview_mesh)
            self.assertNotIn("positions", preview_mesh)
            Path(str(payload["output_path"])).write_bytes(b"preview")
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "preview_geometry",
                "vertex_count": 4,
                "geometry_size": 7,
                "batches": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "geometry.bin"
            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            ):
                report = mesh_native_core.write_native_pose_preview_geometry_blob(
                    output_path,
                    mesh=mesh,
                    skeleton=skeleton,
                    pose_rotations={0: (0.0, 0.0, 90.0)},
                )

        self.assertIsNotNone(report)
        self.assertEqual(["pose-preview-json", "preview-geometry-json"], commands)

    def test_pose_preview_blocks_python_deform_fallback_when_native_available(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh_native_core.clear_native_mesh_core_fallback_counts()
        mesh = _quad_mesh()
        vertex_count = len(mesh.submeshes[0].vertices)
        mesh.submeshes[0].bone_indices = [(0,)] * vertex_count
        mesh.submeshes[0].bone_weights = [(1.0,)] * vertex_count
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="large-pose-preview-native-fail", mode="edit")
        service.attach_skeleton(view.session_id, Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1))
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_pose_preview", return_value=None),
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.mesh_pose_deformed_vertices", side_effect=AssertionError("python pose skinning fallback reached")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python pose preview fallback is disabled"):
                service.pose_preview_mesh(view.session_id)

        self.assertEqual(1, mesh_native_core.native_mesh_core_fallback_counts().get("preview.pose_deform.blocked"))

    def test_selected_vertex_weight_adjust_uses_native_before_python_loop(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.5, 0.5), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-weight-adjust", mode="edit")
        service.attach_skeleton(
            view.session_id,
            Skeleton(
                bones=[
                    Bone(index=0, name="Root"),
                    Bone(index=1, name="Spine"),
                ],
                bone_count=2,
            ),
        )
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )
        service.select_bone(view.session_id, 1)

        def native_weight_edit(mesh_arg: ParsedMesh, vertex_map: Mapping[int, Iterable[int]], **kwargs: object) -> tuple[set[int], dict[int, set[int]]]:
            self.assertEqual("adjust", kwargs.get("operation"))
            self.assertEqual(1, kwargs.get("bone_index"))
            self.assertAlmostEqual(0.2, float(kwargs.get("delta") or 0.0))
            self.assertEqual({0: {2}}, {index: set(vertices) for index, vertices in vertex_map.items()})
            mesh_arg.submeshes[0].bone_indices[2] = (0, 1)
            mesh_arg.submeshes[0].bone_weights[2] = (0.3, 0.7)
            return {0}, {0: {2}}

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", side_effect=native_weight_edit) as native_edit,
            patch("cdmw.services.mesh_service._nudge_bone_weight", side_effect=AssertionError("python weight loop reached")),
        ):
            summary = service.adjust_selected_vertex_bone_weight(view.session_id, 0.2)

        native_edit.assert_called_once()
        self.assertAlmostEqual(0.7, summary.selected_vertex_weights[0].selected_bone_weight)
        self.assertEqual((0, 1), service.working_mesh(view.session_id).submeshes[0].bone_indices[2])
        self.assertEqual((0.3, 0.7), service.working_mesh(view.session_id).submeshes[0].bone_weights[2])
        self.assertEqual(1, service.session_view(view.session_id).undo_count)

    def test_native_selected_vertex_weight_history_uses_native_snapshot_before_clone(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.5, 0.5), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-weight-history", mode="edit")
        service.attach_skeleton(
            view.session_id,
            Skeleton(bones=[Bone(index=0, name="Root"), Bone(index=1, name="Spine")], bone_count=2),
        )
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )
        service.select_bone(view.session_id, 1)
        native_snapshot = {
            "kind": "native_submesh_snapshot",
            "mesh": {},
            "handle": {"id": "weight-snapshot-1", "submesh_count": 1, "vertex_count": 4, "face_count": 2},
            "submeshes": [],
        }

        def native_weight_edit(mesh_arg: ParsedMesh, _vertex_map: Mapping[int, Iterable[int]], **_kwargs: object) -> tuple[set[int], dict[int, set[int]]]:
            mesh_arg.submeshes[0].bone_indices[2] = (0, 1)
            mesh_arg.submeshes[0].bone_weights[2] = (0.25, 0.75)
            return {0}, {0: {2}}

        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", side_effect=native_weight_edit),
        ):
            summary = service.adjust_selected_vertex_bone_weight(view.session_id, 0.25)

        snapshot = service._sessions[view.session_id].undo_stack[0]
        self.assertAlmostEqual(0.75, summary.selected_vertex_weights[0].selected_bone_weight)
        self.assertIsNone(snapshot.mesh)
        self.assertEqual(native_snapshot, snapshot.native_submesh_snapshot)

    def test_selected_vertex_weight_normalize_uses_native_before_python_loop(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (2.0, 1.0), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-weight-normalize", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )

        def native_weight_edit(mesh_arg: ParsedMesh, vertex_map: Mapping[int, Iterable[int]], **kwargs: object) -> tuple[set[int], dict[int, set[int]]]:
            self.assertEqual("normalize", kwargs.get("operation"))
            self.assertEqual({0: {2}}, {index: set(vertices) for index, vertices in vertex_map.items()})
            mesh_arg.submeshes[0].bone_indices[2] = (0, 1)
            mesh_arg.submeshes[0].bone_weights[2] = (2.0 / 3.0, 1.0 / 3.0)
            return {0}, {0: {2}}

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", side_effect=native_weight_edit) as native_edit,
            patch("cdmw.services.mesh_service._normalize_weight_row", side_effect=AssertionError("python normalize loop reached")),
        ):
            service.normalize_selected_vertex_weights(view.session_id)

        native_edit.assert_called_once()
        self.assertEqual((0, 1), service.working_mesh(view.session_id).submeshes[0].bone_indices[2])
        self.assertAlmostEqual(2.0 / 3.0, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][0])
        self.assertAlmostEqual(1.0 / 3.0, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][1])
        self.assertEqual(1, service.session_view(view.session_id).undo_count)

    def test_dirty_native_skeleton_paths_block_python_mesh_reads(self) -> None:
        mesh = _quad_mesh()
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="dirty-skeleton-summary", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)
        skeleton = Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1)
        clip = MeshAnimationClip(source="dirty_clip.paa.json", duration_seconds=1.0)

        with (
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("skeleton pruned stale Python mesh")),
            self.assertRaisesRegex(RuntimeError, "skeleton summary unavailable"),
        ):
            service.skeleton_summary(view.session_id)
        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", side_effect=AssertionError("skin weights mutated stale Python mesh")),
            self.assertRaisesRegex(RuntimeError, "skin weight edit unavailable"),
        ):
            service.normalize_selected_vertex_weights(view.session_id)
        with (
            patch("cdmw.services.mesh_service._clone_mesh_for_service_native_snapshot", side_effect=AssertionError("pose preview cloned stale Python mesh")),
            self.assertRaisesRegex(RuntimeError, "pose preview unavailable"),
        ):
            service.pose_preview_mesh(view.session_id)
        with self.assertRaisesRegex(RuntimeError, "skeleton controls unavailable"):
            service.attach_skeleton(view.session_id, skeleton)
        with self.assertRaisesRegex(RuntimeError, "skeleton controls unavailable"):
            service.set_pose_preview(view.session_id, True)
        with self.assertRaisesRegex(RuntimeError, "skeleton controls unavailable"):
            service.attach_animation_clip(view.session_id, clip)

        self.assertIsNone(session.skeleton)
        self.assertFalse(session.pose_preview_enabled)
        self.assertIsNone(session.animation_clip)

    def test_skin_weight_edit_blocks_python_fallback_when_native_available(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        vertex_count = len(mesh.submeshes[0].vertices)
        mesh.submeshes[0].bone_indices = [(0,)] * vertex_count
        mesh.submeshes[0].bone_weights = [(1.0,)] * vertex_count
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="strict-skin-weight-fallback", mode="edit")
        service.attach_skeleton(view.session_id, Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1))
        service.select_bone(view.session_id, 0)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: range(vertex_count)})),
        )
        native_snapshot = {
            "kind": "native_submesh_snapshot",
            "mesh": {},
            "handle": {"id": "strict-skin-weight-snapshot", "submesh_count": 1, "vertex_count": vertex_count, "face_count": 1},
            "submeshes": [],
        }

        mesh_native_core.clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot"),
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", return_value=None),
            patch("cdmw.services.mesh_service._nudge_bone_weight", side_effect=AssertionError("python weight adjust loop reached")),
            patch("cdmw.services.mesh_service._normalize_weight_row", side_effect=AssertionError("python weight normalize loop reached")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python skin weight fallback is disabled"):
                service.adjust_selected_vertex_bone_weight(view.session_id, 0.1)
            with self.assertRaisesRegex(RuntimeError, "Python skin weight fallback is disabled"):
                service.normalize_selected_vertex_weights(view.session_id)

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot"),
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.transfer_native_mesh_skin_weights_from_source", return_value=None),
            patch("cdmw.services.mesh_service._source_vertex_index_for_transfer", side_effect=AssertionError("python weight transfer loop reached")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python skin weight fallback is disabled"):
                service.transfer_selected_vertex_weights_from_source(view.session_id)

        fallback_counts = mesh_native_core.native_mesh_core_fallback_counts()
        self.assertEqual(1, fallback_counts["skin_weights.adjust.blocked"])
        self.assertEqual(1, fallback_counts["skin_weights.normalize.blocked"])
        self.assertEqual(1, fallback_counts["skin_weights.transfer.blocked"])
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_skin_weight_edit_fails_loudly_when_native_unavailable(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,)] * len(mesh.submeshes[0].vertices)
        mesh.submeshes[0].bone_weights = [(1.0,)] * len(mesh.submeshes[0].vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="strict-skin-weight-native-missing", mode="edit")
        service.attach_skeleton(view.session_id, Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1))
        service.select_bone(view.session_id, 0)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
        )
        native_snapshot = {
            "kind": "native_submesh_snapshot",
            "mesh": {},
            "handle": {"id": "strict-skin-weight-native-missing-snapshot", "submesh_count": 1, "vertex_count": 4, "face_count": 2},
            "submeshes": [],
        }

        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False),
            patch("cdmw.services.mesh_service.apply_native_mesh_skin_weights", return_value=None),
            patch("cdmw.services.mesh_service._nudge_bone_weight", side_effect=AssertionError("python weight adjust loop reached")),
            self.assertRaisesRegex(RuntimeError, "Python skin weight fallback is disabled"),
        ):
            service.adjust_selected_vertex_bone_weight(view.session_id, 0.1)

    def test_native_skin_weight_report_accepts_compact_changed_range(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0,), (1,), (2,), (3,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            counts_path = temp_root / "counts.bin"
            indices_path = temp_root / "indices.bin"
            weights_path = temp_root / "weights.bin"
            counts_path.write_bytes(array("i", (1, 2, 1, 1)).tobytes())
            indices_path.write_bytes(array("i", (0, 0, 1, 2, 3)).tobytes())
            weights_path.write_bytes(array("d", (1.0, 0.25, 0.75, 1.0, 1.0)).tobytes())
            report = {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "skin_weights",
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 4,
                        "changed_count": 2,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                        "bone_counts_binary": {"path": str(counts_path), "count": 4, "components": 1, "type": "i32"},
                        "bone_indices_binary": {"path": str(indices_path), "count": 5, "components": 1, "type": "i32"},
                        "bone_weights_binary": {"path": str(weights_path), "count": 5, "components": 1, "type": "f64"},
                    }
                ],
            }

            affected, changed = mesh_native_core._apply_native_skin_weight_report(mesh, report, {0: 4})

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(1, 3)}, changed)
        self.assertNotIn("changed_vertices_binary", report["submeshes"][0])
        self.assertEqual([(0,), (0, 1), (2,), (3,)], submesh.bone_indices)
        self.assertEqual([(1.0,), (0.25, 0.75), (1.0,), (1.0,)], submesh.bone_weights)

    def test_native_skin_weight_bridge_preserves_range_selection_payload(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0,), (1,), (2,), (3,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("skin-weights-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("bone_counts_binary", submesh_payload)
            self.assertNotIn("bone_indices_binary", submesh_payload)
            self.assertNotIn("bone_weights_binary", submesh_payload)
            counts_path = Path(str(submesh_payload["bone_counts_output_path"]))
            indices_path = Path(str(submesh_payload["bone_indices_output_path"]))
            weights_path = Path(str(submesh_payload["bone_weights_output_path"]))
            counts_path.write_bytes(array("i", (1, 2, 1, 1)).tobytes())
            indices_path.write_bytes(array("i", (0, 0, 1, 2, 3)).tobytes())
            weights_path.write_bytes(array("d", (1.0, 0.5, 0.5, 1.0, 1.0)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "skin_weights",
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 4,
                        "changed_count": 2,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                        "bone_counts_binary": {"path": str(counts_path), "count": 4, "components": 1, "type": "i32"},
                        "bone_indices_binary": {"path": str(indices_path), "count": 5, "components": 1, "type": "i32"},
                        "bone_weights_binary": {"path": str(weights_path), "count": 5, "components": 1, "type": "f64"},
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_skin_weights(
                mesh,
                {0: range(1, 3)},
                operation="normalize",
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(1, 3)}, changed)
        self.assertEqual([(0,), (0, 1), (2,), (3,)], submesh.bone_indices)

    def test_native_skin_weight_bridge_requires_target_session(self) -> None:
        from cdmw.modding import mesh_native_core

        target = _quad_mesh()
        source = _quad_mesh()
        vertex_count = len(target.submeshes[0].vertices)
        target.submeshes[0].bone_indices = [(0,)] * vertex_count
        target.submeshes[0].bone_weights = [(1.0,)] * vertex_count
        source.submeshes[0].bone_indices = [(0,)] * vertex_count
        source.submeshes[0].bone_weights = [(1.0,)] * vertex_count

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=AssertionError("skin-weight job used Python target payload")),
        ):
            self.assertIsNone(
                mesh_native_core.apply_native_mesh_skin_weights(
                    target,
                    {0: (0,)},
                    operation="normalize",
                )
            )
            self.assertIsNone(
                mesh_native_core.transfer_native_mesh_skin_weights_from_source(
                    target,
                    source,
                    {0: (0,)},
                )
            )

    def test_native_region_volume_delta_uses_resident_session_before_vertex_iteration(self) -> None:
        from cdmw.modding import mesh_native_core

        class VertexSequence:
            def __len__(self) -> int:
                return 4

            def __iter__(self):
                raise AssertionError("region volume native session path iterated vertices")

        mesh = _quad_mesh()
        mesh.submeshes[0].vertices = VertexSequence()  # type: ignore[assignment]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("region-volume-delta-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            deltas_path = Path(str(submesh_payload["deltas_output_path"]))
            deltas_path.write_bytes(array("d", (0.0, 0.0, 0.25) * 4).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "region_volume_delta",
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 4,
                        "deltas_binary": {"path": str(deltas_path), "count": 4, "components": 3, "type": "f64"},
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            deltas = mesh_native_core.build_native_region_volume_delta(mesh, {0: range(1, 3)}, 0.25, 1)

        self.assertEqual(((0.0, 0.0, 0.25),) * 4, deltas[0])

    def test_pose_preview_mesh_recomputes_deformed_normals_native_first(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="pose-preview-native-normals", mode="edit")
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        service.attach_skeleton(view.session_id, skeleton)
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_recalculate_normals", return_value={0}) as native_normals,
            patch("cdmw.services.mesh_service.recompute_mesh_normals", side_effect=AssertionError("python normal fallback")),
        ):
            preview = service.pose_preview_mesh(view.session_id)

        native_normals.assert_called_once()
        self.assertEqual({0}, set(native_normals.call_args.args[1]))
        self.assertAlmostEqual(0.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(1.0, preview.submeshes[0].vertices[1][1], places=6)

    def test_pose_preview_mesh_blocks_python_normal_fallback_when_native_unavailable(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh_native_core.clear_native_mesh_core_fallback_counts()
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="pose-preview-native-normal-fail", mode="edit")
        service.attach_skeleton(view.session_id, Skeleton(bones=[Bone(index=0, name="Root")], bone_count=1))
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))
        native_vertices = {0: [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (-1.0, 1.0, 0.0)]}

        with (
            patch("cdmw.services.mesh_service.apply_native_mesh_pose_preview", return_value=native_vertices),
            patch("cdmw.services.mesh_service.apply_native_mesh_recalculate_normals", return_value=None),
            patch("cdmw.services.mesh_service.recompute_mesh_normals", side_effect=AssertionError("python normal fallback")),
            self.assertRaisesRegex(RuntimeError, "Python pose preview fallback is disabled"),
        ):
            service.pose_preview_mesh(view.session_id)

        self.assertEqual(1, mesh_native_core.native_mesh_core_fallback_counts().get("preview.pose_normals.blocked"))
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_animation_clip_document_bridge_accepts_explicit_bone_tracks(self) -> None:
        document = {
            "source": {"path": "object/animation/animation/test_idle_00.paa.json"},
            "summary": {"duration_seconds": 1.0, "frame_rate": 60.0, "frame_rate_confidence": "proven"},
            "animation": {
                "parser_mode": "unit_explicit_tracks",
                "bone_tracks": [
                    {
                        "bone_name": "Root",
                        "rotation_keyframes": [
                            {"time_seconds": 0.0, "rotation_degrees": (0.0, 0.0, 0.0)},
                            {"time_seconds": 1.0, "rotation_degrees": (0.0, 0.0, 90.0)},
                        ],
                    }
                ],
            },
        }

        clip = mesh_animation_clip_from_document(document)

        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertEqual("object/animation/animation/test_idle_00.paa.json", clip.source)
        self.assertEqual("unit_explicit_tracks", clip.parser_mode)
        self.assertEqual(60.0, clip.frame_rate)
        self.assertEqual("proven", clip.timing_confidence)
        self.assertEqual("document_frame_rate_proven", clip.timing_status)
        self.assertTrue(clip.game_accurate_timing)
        self.assertEqual(1, len(clip.tracks))
        self.assertEqual("Root", clip.tracks[0].bone_name)
        self.assertAlmostEqual(1.0, clip.duration_seconds)
        self.assertAlmostEqual(90.0, clip.tracks[0].rotation_keyframes[-1].rotation_degrees[2])

    def test_animation_clip_document_bridge_rejects_archive_only_keyframe_tables(self) -> None:
        document = {
            "source": {"path": "object/animation/animation/test_idle_00.paa"},
            "animation": {
                "keyframe_table_candidates": [
                    {
                        "offset": 64,
                        "row_format": "u16 frame + 4 half-float values",
                        "preview_rows": [
                            {"frame": 1, "values": [0.1, 0.0, 0.0, 0.99]},
                        ],
                    }
                ]
            },
        }

        self.assertIsNone(mesh_animation_clip_from_document(document))

    def test_animation_playback_samples_parsed_clip_into_preview_deformation(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="animation-preview", mode="edit")
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        service.attach_skeleton(view.session_id, skeleton)
        clip = MeshAnimationClip(
            source="safe_clip.paa.json",
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
                    sequence_path="sequencer/binary__/unit_combo.paseqc",
                    clip_path="safe_clip.paa.json",
                    lane_index=7,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                    field_confidence=(("clip_path", "proven"), ("blend_weight", "unknown")),
                ),
            ),
            parser_mode="unit_safe_parser",
            frame_rate=60.0,
            timing_confidence="proven",
            timing_status="unit_sequence_fps_proven",
        )

        attached = service.attach_animation_clip(view.session_id, clip)
        playing = service.set_animation_playback(view.session_id, True)
        sampled = service.seek_animation(view.session_id, 0.5)
        preview = service.pose_preview_mesh(view.session_id)

        self.assertTrue(attached.animation_playback_ready)
        self.assertTrue(playing.animation_playback.enabled)
        self.assertEqual("playback_ready", sampled.animation_status)
        self.assertEqual("safe_clip.paa.json", sampled.animation_playback.source)
        self.assertEqual(60.0, sampled.animation_playback.frame_rate)
        self.assertEqual("proven", sampled.animation_playback.timing_confidence)
        self.assertEqual("unit_sequence_fps_proven", sampled.animation_playback.timing_status)
        self.assertTrue(sampled.animation_playback.game_accurate_timing)
        self.assertEqual(1, sampled.animation_playback.sequence_segment_count)
        self.assertEqual(7, sampled.animation_playback.active_sequence_lane_index)
        self.assertEqual("sequencer/binary__/unit_combo.paseqc", sampled.animation_playback.active_sequence_path)
        self.assertEqual("safe_clip.paa.json", sampled.animation_playback.active_sequence_clip_path)
        self.assertEqual(
            "paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
            sampled.animation_playback.active_sequence_status,
        )
        self.assertEqual("proven", dict(sampled.animation_playback.active_sequence_field_confidence)["clip_path"])
        loop_off = service.set_animation_loop(view.session_id, False)
        speeded = service.set_animation_speed(view.session_id, 2.0)
        advanced = service.step_animation(view.session_id, 0.25)
        scrubbed = service.scrub_animation_fraction(view.session_id, 0.25)
        paused = service.set_animation_playback(view.session_id, False)
        authoring = {row.feature: row for row in sampled.authoring_status_rows}
        self.assertEqual("preview-only", authoring["Animation playback"].state)
        self.assertEqual("proven", authoring["Animation playback"].confidence)
        self.assertIn("unit_sequence_fps_proven", authoring["Animation playback"].detail)
        self.assertAlmostEqual(0.5, sampled.animation_playback.time_seconds)
        self.assertFalse(loop_off.animation_playback.loop)
        self.assertEqual(2.0, speeded.animation_playback.playback_speed)
        self.assertAlmostEqual(1.0, advanced.animation_playback.time_seconds)
        self.assertAlmostEqual(0.25, scrubbed.animation_playback.time_seconds)
        self.assertFalse(paused.animation_playback.enabled)
        self.assertAlmostEqual(2 ** 0.5 / 2.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(2 ** 0.5 / 2.0, preview.submeshes[0].vertices[1][1], places=6)
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_animation_playback_blocks_clip_without_attached_skeleton(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="animation-no-skeleton", mode="edit")
        clip = MeshAnimationClip(
            source="safe_clip.paa.json",
            duration_seconds=1.0,
            tracks=(
                MeshAnimationTrack(
                    bone_index=0,
                    rotation_keyframes=(MeshAnimationKeyframe(0.0, (0.0, 0.0, 15.0)),),
                ),
            ),
        )

        summary = service.attach_animation_clip(view.session_id, clip)
        playing = service.set_animation_playback(view.session_id, True)

        self.assertFalse(summary.animation_playback_ready)
        self.assertEqual("playback_blocked", summary.animation_status)
        self.assertTrue(any("attached parsed skeleton" in blocker for blocker in summary.animation_blockers))
        self.assertFalse(playing.animation_playback.enabled)

    def test_transfer_selected_part_weights_from_source(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="part-weight-transfer", mode="edit")
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        summary = service.transfer_selected_vertex_weights_from_source(view.session_id)

        self.assertTrue(summary.skinned)
        self.assertEqual([(0,), (1,), (0, 1), (1,)], working.submeshes[0].bone_indices)
        self.assertEqual([(1.0,), (1.0,), (0.25, 0.75), (1.0,)], working.submeshes[0].bone_weights)
        self.assertEqual(1, service.session_view(view.session_id).undo_count)

    def test_transfer_selected_weights_can_remap_bones_by_name(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="mapped-weight-transfer", mode="edit")
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        source_skeleton = Skeleton(
            bones=[
                Bone(index=0, name="Root"),
                Bone(index=1, name="Spine"),
            ],
            bone_count=2,
        )
        target_skeleton = Skeleton(
            bones=[
                Bone(index=4, name="Spine"),
                Bone(index=9, name="Root"),
            ],
            bone_count=2,
        )
        service.attach_skeleton(view.session_id, target_skeleton)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )

        summary = service.transfer_selected_vertex_weights_from_source(view.session_id, source_skeleton=source_skeleton)

        self.assertEqual((4, 9), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.75, 0.25), working.submeshes[0].bone_weights[2])
        self.assertEqual(9, summary.parts[0].max_bone_index)
        self.assertAlmostEqual(0.0, summary.selected_vertex_weights[0].selected_bone_weight)

    def test_transfer_selected_weights_uses_native_before_python_source_lookup(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-weight-transfer", mode="edit")
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )

        def native_transfer(
            target_mesh: ParsedMesh,
            source_mesh: ParsedMesh,
            vertex_map: Mapping[int, Iterable[int]],
            selected_all_submeshes: Iterable[int],
            **kwargs: object,
        ) -> tuple[set[int], dict[int, set[int]]]:
            self.assertIs(target_mesh, working)
            self.assertEqual("quad.pac", source_mesh.path)
            self.assertEqual({0: {2}}, {index: set(vertices) for index, vertices in vertex_map.items()})
            self.assertEqual(set(), set(selected_all_submeshes))
            self.assertIsNone(kwargs.get("bone_remap"))
            target_mesh.submeshes[0].bone_indices[2] = (0, 1)
            target_mesh.submeshes[0].bone_weights[2] = (0.25, 0.75)
            return {0}, {0: {2}}

        with (
            patch("cdmw.services.mesh_service.transfer_native_mesh_skin_weights_from_source", side_effect=native_transfer) as native_edit,
            patch("cdmw.services.mesh_service._source_vertex_index_for_transfer", side_effect=AssertionError("python source lookup reached")),
        ):
            summary = service.transfer_selected_vertex_weights_from_source(view.session_id)

        native_edit.assert_called_once()
        self.assertTrue(summary.skinned)
        self.assertEqual((0, 1), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.25, 0.75), working.submeshes[0].bone_weights[2])
        self.assertEqual(1, service.session_view(view.session_id).undo_count)

    def test_compare_summary_reports_material_uv_bounds_and_topology_differences(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="compare-summary", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.material = "mat_changed"
        edited.texture = "changed.dds"
        edited.uvs[0] = (0.25, 0.25)
        edited.vertices[3] = (2.0, 1.0, 0.0)
        edited.faces.append((0, 1, 2))
        edited.face_count = len(edited.faces)

        summary = service.compare_summary(view.session_id)

        self.assertTrue(summary.changed)
        self.assertTrue(summary.topology_changed)
        self.assertTrue(summary.bounds_changed)
        self.assertGreater(summary.scale_ratio, 1.0)
        self.assertEqual(1, summary.material_mismatch_count)
        self.assertEqual(1, summary.texture_mismatch_count)
        self.assertEqual(1, summary.uv_mismatch_count)
        self.assertEqual(1, summary.bounds_mismatch_count)
        self.assertEqual("topology, material, texture, uv, bounds", summary.parts[0].change_text)

    def test_dirty_native_compare_summary_blocks_python_sync(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-compare-summary", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)

        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("compare hydrated Python mesh")),
            self.assertRaisesRegex(RuntimeError, "compare summary unavailable"),
        ):
            service.compare_summary(view.session_id)

    def test_cleanup_tools_repair_doubles_loose_vertices_winding_holes_and_display_faces(self) -> None:
        service = MeshService()
        cleanup_mesh = _duplicate_vertex_mesh()
        cleanup_submesh = cleanup_mesh.submeshes[0]
        cleanup_submesh.vertices.append((99.0, 99.0, 99.0))
        cleanup_submesh.uvs.append((0.0, 0.0))
        cleanup_submesh.normals.append((0.0, 0.0, 1.0))
        cleanup_submesh.vertex_count = len(cleanup_submesh.vertices)
        cleanup_mesh.total_vertices = len(cleanup_submesh.vertices)
        view = service.open_edit_session(cleanup_mesh, session_id="cleanup-doubles", mode="edit")

        removed = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "remove_doubles",
                mode="edit",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"threshold": 0.001},
            ),
        )
        cleaned = service.working_mesh(view.session_id).submeshes[0]

        self.assertTrue(removed.topology_changed)
        self.assertEqual((0,), removed.affected_submesh_indices)
        self.assertEqual(4, cleaned.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], cleaned.faces)

        winding_mesh = _triangle_mesh()
        winding_mesh.submeshes[0].faces = [(0, 2, 1)]
        winding_view = service.open_edit_session(winding_mesh, session_id="cleanup-winding", mode="edit")
        winding = service.apply_command(winding_view.session_id, MeshEditCommand("fix_winding", mode="edit"))
        self.assertTrue(winding.topology_changed)
        self.assertEqual([(0, 1, 2)], service.working_mesh(winding_view.session_id).submeshes[0].faces)

        hole_submesh = SubMesh(
            name="open_tetra",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 3), (1, 2, 3), (2, 0, 3)],
            vertex_count=4,
            face_count=3,
        )
        hole_mesh = ParsedMesh(path="hole.pac", format="pac", submeshes=[hole_submesh], total_vertices=4, total_faces=3)
        hole_view = service.open_edit_session(hole_mesh, session_id="cleanup-hole", mode="edit")
        filled = service.apply_command(hole_view.session_id, MeshEditCommand("fill_holes", mode="edit"))
        self.assertTrue(filled.topology_changed)
        self.assertEqual(4, service.working_mesh(hole_view.session_id).submeshes[0].face_count)

        display_mesh = _quad_mesh()
        display_mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]
        display_view = service.open_edit_session(display_mesh, session_id="cleanup-triangulate", mode="edit")
        triangulated = service.apply_command(
            display_view.session_id,
            MeshEditCommand("triangulate_display", mode="edit", params={"allow_legacy_display_cleanup": True}),
        )
        self.assertTrue(triangulated.topology_changed)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], service.working_mesh(display_view.session_id).submeshes[0].faces)

    def test_triangulate_display_requires_explicit_legacy_opt_in(self) -> None:
        service = MeshService()
        display_mesh = _quad_mesh()
        display_mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]
        view = service.open_edit_session(display_mesh, session_id="active-triangulate-display", mode="edit")

        with self.assertRaisesRegex(RuntimeError, "legacy display-shape cleanup"):
            service.apply_command(view.session_id, MeshEditCommand("triangulate_display", mode="edit"))

    def test_dirty_native_blocks_legacy_display_cleanup_even_with_opt_in(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dirty-legacy-display-cleanup", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)

        with (
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("legacy cleanup hydrated dirty native mesh")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("legacy cleanup mutated Python mesh")),
            self.assertRaisesRegex(RuntimeError, "cannot run while native mesh state is dirty"),
        ):
            service.apply_command(
                view.session_id,
                MeshEditCommand("triangulate_display", mode="edit", params={"allow_legacy_display_cleanup": True}),
            )

    def test_triangulate_display_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        display_mesh = _quad_mesh()
        display_mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]
        view = service.open_edit_session(display_mesh, session_id="native-triangulate-display", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        calls: list[set[int]] = []

        def native_triangulate(
            target_mesh: ParsedMesh,
            submesh_indices: object = None,
            **_kwargs: object,
        ) -> set[int]:
            calls.append(set(submesh_indices or ()))  # type: ignore[arg-type]
            target = target_mesh.submeshes[0]
            target.faces = [(0, 1, 3), (0, 3, 2)]
            target.face_count = 2
            return {0}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_triangulate_display", side_effect=native_triangulate),
            patch("cdmw.modding.mesh_edit_ops._coerce_index", side_effect=AssertionError("python triangulate loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("triangulate_display", mode="edit", params={"allow_legacy_display_cleanup": True}),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual([{0}], calls)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], working.submeshes[0].faces)

    def test_duplicate_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-duplicate", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        calls: list[tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[tuple[int, int]]]]] = []

        def native_duplicate(
            target_mesh: ParsedMesh,
            selected_faces_by_submesh: Mapping[int, set[int]],
            selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
            **kwargs: object,
        ) -> tuple[set[int], dict[int, int]]:
            calls.append(
                (
                    {index: set(values) for index, values in selected_faces_by_submesh.items()},
                    {index: set(values) for index, values in (selected_vertices_by_submesh or {}).items()},
                    {
                        index: set(values)
                        for index, values in (kwargs.get("selected_edges_by_submesh") or {}).items()  # type: ignore[union-attr]
                    },
                )
            )
            source = target_mesh.submeshes[0]
            target_mesh.submeshes.append(
                SubMesh(
                    name="quad duplicate",
                    material=source.material,
                    texture=source.texture,
                    vertices=[source.vertices[0], source.vertices[1], source.vertices[2]],
                    uvs=[source.uvs[0], source.uvs[1], source.uvs[2]],
                    normals=[source.normals[0], source.normals[1], source.normals[2]],
                    faces=[(0, 1, 2)],
                    vertex_count=3,
                    face_count=1,
                )
            )
            return {1}, {1: 0}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_duplicate", side_effect=AssertionError("legacy duplicate helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python duplicate face expansion reached")),
            patch("cdmw.modding.mesh_edit_ops._append_face_copy", side_effect=AssertionError("python duplicate copy loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((1,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(1, len(working.submeshes))
        refreshed = service.working_mesh(view.session_id)
        self.assertEqual(2, len(refreshed.submeshes))
        self.assertEqual([(0, 1, 2)], refreshed.submeshes[1].faces)

    def test_mirror_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-mirror", mode="edit")

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_mirror", side_effect=AssertionError("legacy mirror helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python mirror face expansion reached")),
            patch("cdmw.modding.mesh_edit_ops._append_mirrored_face_copy", side_effect=AssertionError("python mirror copy loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={"axis": "x"}),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((1,), result.affected_submesh_indices)
        mesh = service.working_mesh(view.session_id)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual([(0, 2, 1)], mesh.submeshes[1].faces)

    def test_in_place_mirror_param_uses_native_mirror_without_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-in-place-mirror", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        calls: list[tuple[dict[int, set[int]], dict[int, set[tuple[int, int]]], dict[int, set[int]], tuple[float, float, float]]] = []

        def native_transform_selection(
            target_mesh: ParsedMesh,
            *,
            vertices_by_submesh: Mapping[int, set[int]],
            edges_by_submesh: Mapping[int, set[tuple[int, int]]],
            faces_by_submesh: Mapping[int, set[int]],
            scale: tuple[float, float, float],
            **_kwargs: object,
        ) -> dict[int, set[int]]:
            calls.append(
                (
                    {index: set(values) for index, values in vertices_by_submesh.items()},
                    {index: set(values) for index, values in edges_by_submesh.items()},
                    {index: set(values) for index, values in faces_by_submesh.items()},
                    scale,
                )
            )
            target_mesh.submeshes[0].vertices[1] = (-1.0, 0.0, 0.0)
            return {0: {1}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", side_effect=AssertionError("legacy transform helper")),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_recalculate_normals", side_effect=AssertionError("legacy normal helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python mirror vertex expansion reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "mirror",
                    selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                    params={"axis": "x", "in_place": True},
                ),
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((1,), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(1, len(working.submeshes))
        refreshed = service.working_mesh(view.session_id)
        self.assertEqual(2, len(refreshed.submeshes))
        self.assertEqual((-1.0, 0.0, 0.0), refreshed.submeshes[1].vertices[1])

    def test_separate_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-separate", mode="edit")

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_separate", side_effect=AssertionError("legacy separate helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python separate face expansion reached")),
            patch("cdmw.modding.mesh_edit_ops.split_faces_to_submesh", side_effect=AssertionError("python separate split loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("separate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0, 1), result.affected_submesh_indices)
        mesh = service.working_mesh(view.session_id)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual([(0, 2, 1)], mesh.submeshes[0].faces)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[1].faces)

    def test_remove_doubles_uses_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="native-cleanup", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("remove_doubles must use resident native editor session"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "remove_doubles",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(source_indices=(0,)),
                    params={"threshold": 0.001},
                ),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_remove_doubles_source_selection_uses_native_all_vertices_before_python_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="native-cleanup-source", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with (
            patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("remove_doubles legacy geometry reached"),
            ),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python cleanup source vertex expansion reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "remove_doubles",
                    selection=MeshEditSelection.from_maps(source_indices=(0,)),
                    mode="edit",
                    params={"threshold": 0.001},
                ),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, service.working_mesh(view.session_id).submeshes[0].vertex_count)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_delete_loose_vertices_uses_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].vertices.append((2.0, 2.0, 2.0))
        mesh.submeshes[0].uvs.append((0.5, 0.5))
        mesh.submeshes[0].normals.append((0.0, 0.0, 1.0))
        mesh.submeshes[0].vertex_count = 5
        mesh.total_vertices = 5
        view = service.open_edit_session(mesh, session_id="native-compact-orphans", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("delete_loose_vertices must use resident native editor session"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete_loose_vertices",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(source_indices=(0,)),
                ),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(5, submesh.vertex_count)
        refreshed = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual(4, refreshed.vertex_count)
        self.assertEqual(4, len(refreshed.uvs))
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_fix_winding_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        mesh = _triangle_mesh()
        mesh.submeshes[0].faces = [(0, 2, 1)]
        view = service.open_edit_session(mesh, session_id="native-fix-winding", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        calls: list[tuple[tuple[int, ...], bool]] = []

        def native_fix_winding(
            target_mesh: ParsedMesh,
            submesh_indices: object = None,
            *,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> set[int]:
            calls.append((tuple(submesh_indices or ()), recompute_normals))  # type: ignore[arg-type]
            target_mesh.submeshes[0].faces = [(0, 1, 2)]
            return {0}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_fix_winding", side_effect=AssertionError("legacy fix winding helper")),
            patch("cdmw.modding.mesh_edit_ops._valid_face_items", side_effect=AssertionError("python winding loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("fix_winding", mode="edit"))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([(0, 2, 1)], working.submeshes[0].faces)
        self.assertEqual([(0, 1, 2)], service.working_mesh(view.session_id).submeshes[0].faces)

    def test_fill_holes_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        hole_submesh = SubMesh(
            name="open_tetra",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 3), (1, 2, 3), (2, 0, 3)],
            vertex_count=4,
            face_count=3,
        )
        mesh = ParsedMesh(path="hole.pac", format="pac", submeshes=[hole_submesh], total_vertices=4, total_faces=3)
        view = service.open_edit_session(mesh, session_id="native-fill-holes", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        calls: list[tuple[tuple[int, ...], bool]] = []

        def native_fill_holes(
            target_mesh: ParsedMesh,
            submesh_indices: object = None,
            *,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> set[int]:
            calls.append((tuple(submesh_indices or ()), recompute_normals))  # type: ignore[arg-type]
            target = target_mesh.submeshes[0]
            target.faces = list(target.faces or []) + [(0, 1, 2)]
            target.face_count = len(target.faces)
            return {0}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_fill_holes", side_effect=AssertionError("legacy fill holes helper")),
            patch("cdmw.modding.mesh_edit_ops._boundary_edges", side_effect=AssertionError("python fill holes loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("fill_holes", mode="edit"))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(3, working.submeshes[0].face_count)
        self.assertEqual(4, service.working_mesh(view.session_id).submeshes[0].face_count)

    def test_fill_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="native-fill", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (2, 3), (0, 2))})
        calls: list[tuple[dict[int, set[int]], dict[int, set[tuple[int, int]]], bool]] = []

        def native_fill(
            target_mesh: ParsedMesh,
            selected_vertices_by_submesh: dict[int, set[int]],
            *,
            selected_edges_by_submesh: dict[int, set[tuple[int, int]]] | None = None,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> set[int]:
            calls.append(
                (
                    {index: set(values) for index, values in selected_vertices_by_submesh.items()},
                    {index: set(values) for index, values in (selected_edges_by_submesh or {}).items()},
                    recompute_normals,
                )
            )
            target = target_mesh.submeshes[0]
            target.faces = [(0, 1, 3), (0, 3, 2)]
            target.face_count = 2
            return {0}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_fill", side_effect=AssertionError("legacy fill helper")),
            patch("cdmw.modding.mesh_edit_ops._closed_edge_loop_order", side_effect=AssertionError("python fill loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("fill", selection=selection))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([], working.submeshes[0].faces)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], service.working_mesh(view.session_id).submeshes[0].faces)

    def test_uv_summary_reports_connected_islands_textures_and_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
        )

        summary = service.uv_summary(view.session_id)

        self.assertEqual(2, summary.island_count)
        self.assertEqual(1, summary.selected_island_count)
        self.assertEqual((0.0, 0.0), summary.islands[0].uv_min)
        self.assertEqual((0.5, 0.5), summary.islands[0].uv_max)
        self.assertEqual("uv.dds", summary.islands[0].texture)
        self.assertTrue(summary.islands[0].selected)
        self.assertFalse(summary.islands[1].selected)
        self.assertEqual(3, summary.islands[0].vertex_count)
        self.assertEqual(1, summary.islands[0].face_count)

    def test_uv_summary_keeps_overlapping_disconnected_islands_separate(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_overlapping_uv_island_mesh(), session_id="uv-summary-overlap", mode="edit")

        summary = service.uv_summary(view.session_id)

        self.assertEqual(2, summary.island_count)
        self.assertEqual({(0.0, 0.0)}, {island.uv_min for island in summary.islands})
        self.assertEqual({(1.0, 1.0)}, {island.uv_max for island in summary.islands})

    def test_uv_summary_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="native-uv-summary", mode="edit")
        native_report = {
            "operation": "uv_summary",
            "island_count": 2,
            "selected_island_count": 1,
            "islands": [
                {
                    "index": 0,
                    "submesh_index": 0,
                    "part_name": "uv_islands",
                    "material": "mat",
                    "texture": "uv.dds",
                    "vertex_count": 3,
                    "face_count": 1,
                    "uv_min": [0.0, 0.0],
                    "uv_max": [0.5, 0.5],
                    "selected": True,
                    "selected_vertex_count": 1,
                    "selected_face_count": 0,
                },
                {
                    "index": 1,
                    "submesh_index": 0,
                    "part_name": "uv_islands",
                    "material": "mat",
                    "texture": "uv.dds",
                    "vertex_count": 3,
                    "face_count": 1,
                    "uv_min": [2.0, 0.0],
                    "uv_max": [2.5, 0.5],
                    "selected": False,
                    "selected_vertex_count": 0,
                    "selected_face_count": 0,
                },
            ],
        }

        with (
            patch("cdmw.services.mesh_service.prune_native_mesh_selection", return_value=None),
            patch("cdmw.services.mesh_service.summarize_native_mesh_uvs", return_value=native_report) as native_summary,
            patch("cdmw.services.mesh_service.summarize_mesh_uvs") as python_summary,
        ):
            summary = service.uv_summary(view.session_id)

        self.assertEqual(2, summary.island_count)
        self.assertEqual(1, summary.selected_island_count)
        self.assertEqual((0.0, 0.0), summary.islands[0].uv_min)
        self.assertEqual((0.5, 0.5), summary.islands[0].uv_max)
        self.assertEqual("uv.dds", summary.islands[0].texture)
        self.assertTrue(summary.islands[0].selected)
        self.assertFalse(summary.islands[1].selected)
        native_summary.assert_called_once()
        python_summary.assert_not_called()

    def test_uv_summary_blocks_stale_python_mesh_when_native_session_is_dirty(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="dirty-uv-summary", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((6, 2),)

        with (
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("python selection prune")),
            patch("cdmw.services.mesh_service.summarize_native_mesh_uvs", side_effect=AssertionError("stale native uv summary")),
            patch("cdmw.services.mesh_service.summarize_mesh_uvs", side_effect=AssertionError("python uv summary")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python mesh state is stale"):
                service.uv_summary(view.session_id)

    def test_native_mesh_core_uv_summary_uses_binary_geometry_and_compact_ranges(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _two_uv_island_mesh()
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}, faces_by_submesh={0: (1,)}, source_indices=(0,))

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-summary-json", command)
            self.assertEqual("uv_summary", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("uvs_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["source_face_start"])
            self.assertEqual(2, submesh_payload["source_face_count"])
            self.assertNotIn("source_face_indices_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertTrue(submesh_payload["source_selected"])
            self.assertEqual("uv_islands", submesh_payload["part_name"])
            self.assertEqual(6, submesh_payload["uvs_binary"]["count"])
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["uvs_binary"]["path"]).is_file())
            self.assertTrue(Path(submesh_payload["faces_binary"]["path"]).is_file())
            self.assertEqual(5.0, timeout_seconds)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_summary",
                "island_count": 1,
                "selected_island_count": 1,
                "islands": [
                    {
                        "index": 0,
                        "submesh_index": 0,
                        "part_name": "uv_islands",
                        "material": "mat",
                        "texture": "uv.dds",
                        "vertex_count": 3,
                        "face_count": 1,
                        "uv_min": [0.0, 0.0],
                        "uv_max": [0.5, 0.5],
                        "selected": True,
                        "selected_vertex_count": 1,
                        "selected_face_count": 0,
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            report = mesh_native_core.summarize_native_mesh_uvs(mesh, selection)

        self.assertIsNotNone(report)
        self.assertEqual(1, report["island_count"])  # type: ignore[index]
        self.assertEqual(1, report["selected_island_count"])  # type: ignore[index]

    def test_native_mesh_core_uv_summary_uses_resident_session_without_geometry_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        class ExplodingGeometry:
            def __bool__(self) -> bool:
                raise AssertionError("resident UV summary should not inspect Python geometry")

            def __len__(self) -> int:
                raise AssertionError("resident UV summary should not inspect Python geometry")

            def __iter__(self):
                raise AssertionError("resident UV summary should not inspect Python geometry")

        mesh = _two_uv_island_mesh()
        mesh.submeshes[0].uvs = ExplodingGeometry()  # type: ignore[assignment]
        mesh.submeshes[0].faces = ExplodingGeometry()  # type: ignore[assignment]
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)}, faces_by_submesh={0: (1,)}, source_indices=(0,))

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-summary-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-uv-summary-0", submesh_payload["session_id"])
            self.assertNotIn("uvs_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_summary",
                "island_count": 0,
                "selected_island_count": 0,
                "islands": [],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-uv-summary-0"),
            patch("cdmw.modding.mesh_native_core._write_vec2_binary_payload", side_effect=AssertionError("uv sidecar write")),
            patch("cdmw.modding.mesh_native_core._write_face_binary_payload", side_effect=AssertionError("face sidecar write")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            report = mesh_native_core.summarize_native_mesh_uvs(mesh, selection)

        self.assertIsNotNone(report)
        self.assertEqual(0, report["island_count"])  # type: ignore[index]

    def test_texture_edit_target_uses_selected_textured_part(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        setattr(mesh.submeshes[1], "cdmw_source_texture_set_key", "part_b_set")
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="texture-target", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(1,))),
        )

        target = service.texture_edit_target(view.session_id)

        assert target is not None
        self.assertEqual(1, target.submesh_index)
        self.assertEqual("quad_b", target.part_name)
        self.assertEqual("mat_b", target.material)
        self.assertEqual("b.dds", target.texture)
        self.assertEqual("part_b_set", target.source_texture_set_key)

    def test_texture_edit_target_does_not_fallback_when_selected_part_has_no_texture(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        mesh.submeshes[0].texture = ""
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="texture-target-selected-missing", mode="edit")

        fallback = service.texture_edit_target(view.session_id)
        assert fallback is not None
        self.assertEqual(1, fallback.submesh_index)

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertIsNone(service.texture_edit_target(view.session_id))

    def test_dirty_native_texture_edit_target_uses_native_summary(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].texture = ""
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="texture-target-native-summary", mode="edit")
        session = service._session(view.session_id)
        session.selection = MeshEditSelection.from_maps(source_indices=(0,))
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)
        report = {
            "status": "ok",
            "protocol": "mesh-editor-session-json",
            "command": "summary",
            "submeshes": [
                {
                    "index": 0,
                    "name": "native_quad",
                    "material": "native_mat",
                    "texture": "native.dds",
                    "vertex_count": 4,
                    "face_count": 2,
                    "extra_attrs": {"cdmw_source_texture_set_key": "native_set"},
                }
            ],
        }

        with (
            patch("cdmw.services.mesh_service.summarize_native_mesh_editor_session", return_value=report),
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("dirty native texture query hydrated")),
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("dirty native texture query pruned Python mesh")),
        ):
            target = service.texture_edit_target(view.session_id)

        assert target is not None
        self.assertEqual(0, target.submesh_index)
        self.assertEqual("native_quad", target.part_name)
        self.assertEqual("native_mat", target.material)
        self.assertEqual("native.dds", target.texture)
        self.assertEqual("native_set", target.source_texture_set_key)

    def test_transform_uses_session_selection_and_undo_redo_keeps_original_mesh_clean(self) -> None:
        original = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(original, session_id="edit", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        result = service.apply_command(view.session_id, MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}))

        self.assertTrue(result.ok)
        changed = dict(result.changed_vertices_by_submesh)[0]
        self.assertIsInstance(changed, dict)
        self.assertEqual(2, changed["changed_vertices_binary"]["count"])  # type: ignore[index]
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual((0.0, 0.0, 0.0), original.submeshes[0].vertices[0])

        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertTrue(service.redo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_transform_records_undoable_position_edit_operation(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="edit-operation-history", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        result = service.apply_command(
            view.session_id,
            MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}, label="Move"),
        )
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(result.ok)
        operations = service._sessions[view.session_id].edit_operations
        operation_names = [operation["operation"] for operation in operations]  # type: ignore[index]
        self.assertIn("translate_vertices", operation_names)
        self.assertIn("replace_normals_same_count", operation_names)
        self.assertEqual(0, operations[0]["submesh_index"])  # type: ignore[index]
        self.assertNotIn("untracked_edit_channel", {issue.code for issue in report.blockers})

        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual((), service._sessions[view.session_id].edit_operations)
        self.assertTrue(service.redo(view.session_id).ok)
        redone_operation_names = [operation["operation"] for operation in service._sessions[view.session_id].edit_operations]  # type: ignore[index]
        self.assertIn("translate_vertices", redone_operation_names)

    def test_select_can_add_subtract_and_toggle_existing_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="select-ops", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0,)},
                    edges_by_submesh={0: ((0, 1),)},
                    faces_by_submesh={0: (0,)},
                    source_indices=(0,),
                ),
            ),
        )
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (3,)},
                    edges_by_submesh={0: ((1, 2),)},
                    faces_by_submesh={0: (1,)},
                    source_indices=(1,),
                ),
                params={"operation": "add"},
            ),
        )
        added = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 3}}, added.vertex_map())
        self.assertEqual({0: {(0, 1), (1, 2)}}, added.edge_map())
        self.assertEqual({0: {0, 1}}, added.face_map())
        self.assertEqual((0, 1), added.source_indices)

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0,)},
                    edges_by_submesh={0: ((0, 1),)},
                    faces_by_submesh={0: (0,)},
                    source_indices=(0,),
                ),
                params={"operation": "subtract"},
            ),
        )
        subtracted = service.session_view(view.session_id).selection
        self.assertEqual({0: {3}}, subtracted.vertex_map())
        self.assertEqual({0: {(1, 2)}}, subtracted.edge_map())
        self.assertEqual({0: {1}}, subtracted.face_map())
        self.assertEqual((1,), subtracted.source_indices)

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (2, 3)},
                    edges_by_submesh={0: ((1, 2), (2, 3))},
                    faces_by_submesh={0: (1,)},
                    source_indices=(1, 2),
                ),
                params={"operation": "toggle"},
            ),
        )
        toggled = service.session_view(view.session_id).selection
        self.assertEqual({0: {2}}, toggled.vertex_map())
        self.assertEqual({0: {(2, 3)}}, toggled.edge_map())
        self.assertEqual({}, toggled.face_map())
        self.assertEqual((), toggled.source_indices)

    def test_select_requires_native_core_without_python_selection_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-native-required", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False),
            patch(
                "cdmw.services.mesh_service._apply_selection_operation_to_mesh",
                side_effect=AssertionError("python selection fallback should not run"),
            ),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))

        self.assertFalse(result.ok)
        self.assertEqual("error", result.status)
        self.assertIn("Python selection fallback is blocked", result.diagnostics[0])
        self.assertEqual({}, service.session_view(view.session_id).selection.vertex_map())

    def test_non_native_service_geometry_dispatcher_is_legacy_only(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="non-native-dispatcher", mode="edit")

        with (
            patch("cdmw.services.mesh_service._NATIVE_EDITOR_SESSION_ACTIONS", frozenset()),
            patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("legacy geometry dispatcher should not run"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "unsupported non-native mesh edit action"):
                service.apply_command(view.session_id, MeshEditCommand("remove_doubles", mode="edit"))

    def test_select_prunes_indices_outside_current_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-prune", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0, 99), 4: (0,)},
                    edges_by_submesh={0: ((0, 1), (0, 3), (1, 99)), 4: ((0, 1),)},
                    faces_by_submesh={0: (0, 9), 4: (0,)},
                    source_indices=(0, 4),
                ),
            ),
        )

        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({0: {0}}, selection.face_map())
        self.assertEqual((0,), selection.source_indices)

    def test_select_prunes_malformed_faces_and_non_face_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_malformed_face_mesh(), session_id="select-prune-malformed", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0, 3)},
                    edges_by_submesh={0: ((0, 1), (0, 3))},
                    faces_by_submesh={0: (0, 1, 2)},
                ),
            ),
        )

        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 3}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({}, selection.face_map())

    def test_select_preserves_loose_edges_on_mesh_without_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="select-prune-loose-edge", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3), (1, 99))})),
        )

        self.assertEqual({0: {(0, 3)}}, service.session_view(view.session_id).selection.edge_map())

    def test_select_prunes_through_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-prune-native", mode="edit")

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"metrics": {"cpp_ms": 1.0}}),
            patch(
                "cdmw.services.mesh_service.select_native_mesh_editor_session",
                return_value={
                    "metrics": {"cpp_ms": 1.5, "io_serialization_ms": 0.25},
                    "submeshes": [{"index": 0, "selected_vertices": [0], "selected_edges": [[0, 1]], "selected_faces": [0]}],
                    "source_indices": [0],
                },
            ) as selected,
            patch("cdmw.services.mesh_service.prune_native_mesh_selection", side_effect=AssertionError("obsolete prune path used")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(
                        vertices_by_submesh={0: (0, 99), 4: (0,)},
                        edges_by_submesh={0: ((0, 1), (0, 3), (1, 99)), 4: ((0, 1),)},
                        faces_by_submesh={0: (0, 9), 4: (0,)},
                        source_indices=(0, 4),
                    ),
                ),
            )

        selected.assert_called_once()
        self.assertEqual(1.5, result.metrics["cpp_ms"])
        self.assertEqual(0.25, result.metrics["io_serialization_ms"])
        self.assertEqual("replace", selected.call_args.kwargs["operation"])
        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({0: {0}}, selection.face_map())
        self.assertEqual((0,), selection.source_indices)

    def test_select_operation_combines_current_selection_through_native_prune(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-native-combine", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}, source_indices=(0,))),
        )
        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch(
                "cdmw.services.mesh_service.select_native_mesh_editor_session",
                return_value={
                    "metrics": {"cpp_ms": 3.0},
                    "submeshes": [{"index": 0, "selected_vertices": [0, 2]}],
                    "source_indices": [],
                },
            ) as selected,
            patch("cdmw.services.mesh_service.prune_native_mesh_selection", side_effect=AssertionError("obsolete prune path used")),
        ):
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)}, source_indices=(0,)),
                    params={"operation": "toggle"},
                ),
            )

        selected.assert_called_once()
        self.assertEqual("toggle", selected.call_args.kwargs["operation"])
        self.assertEqual({"vertices_by_submesh": {0: {1, 2}}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": (0,)}, selected.call_args.args[1])
        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        self.assertEqual((), selection.source_indices)

    def test_select_grow_routes_through_native_selection_edit(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-native-grow", mode="edit")
        stop_event = threading.Event()
        incoming = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (0,)},
            edges_by_submesh={0: ((1, 2),)},
            faces_by_submesh={0: (1,)},
            source_indices=(0,),
        )

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"metrics": {"cpp_ms": 1.0}}),
            patch(
                "cdmw.services.mesh_service.select_native_mesh_editor_session",
                return_value={
                    "metrics": {"cpp_ms": 2.5, "io_serialization_ms": 0.75},
                    "submeshes": [{"index": 0, "selected_vertices": [0, 1, 2]}],
                    "source_indices": [],
                },
            ) as native_select_mock,
            patch("cdmw.services.mesh_service.apply_native_mesh_selection", side_effect=AssertionError("one-shot selection path used")),
            patch("cdmw.services.mesh_service.prune_native_mesh_selection", side_effect=AssertionError("prune path used")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("select", selection=incoming, params={"operation": "grow", "stop_event": stop_event}),
            )

        self.assertTrue(result.ok)
        native_select_mock.assert_called_once()
        self.assertIs(native_select_mock.call_args.kwargs["stop_event"], stop_event)
        self.assertEqual("grow", native_select_mock.call_args.kwargs["operation"])
        self.assertEqual(
            {"vertices_by_submesh": {0: {0}}, "edges_by_submesh": {0: {(1, 2)}}, "faces_by_submesh": {0: {1}}, "source_indices": (0,)},
            native_select_mock.call_args.args[1],
        )
        self.assertEqual(2.5, result.metrics["cpp_ms"])
        self.assertEqual(0.75, result.metrics["io_serialization_ms"])
        self.assertEqual(2.5, result.metrics["editor_select_cpp_ms"])
        self.assertEqual(1.0, result.metrics["editor_select_resident_operation"])
        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 1, 2}}, selection.vertex_map())
        self.assertEqual({}, selection.edge_map())
        self.assertEqual({}, selection.face_map())
        self.assertEqual((), selection.source_indices)

    def test_select_syncs_resident_native_editor_session_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-native-editor-sync", mode="edit")
        command = MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}, faces_by_submesh={0: (1,)}),
        )

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"metrics": {"cpp_ms": 2.0}}) as opened,
            patch(
                "cdmw.services.mesh_service.select_native_mesh_editor_session",
                return_value={
                    "metrics": {"cpp_ms": 3.0},
                    "submeshes": [{"index": 0, "selected_vertices": [0], "selected_faces": [1]}],
                    "source_indices": [],
                },
            ) as selected,
            patch("cdmw.services.mesh_service.prune_native_mesh_selection", side_effect=AssertionError("prune path used")),
        ):
            result = service.apply_command(view.session_id, command)

        self.assertTrue(result.ok)
        opened.assert_called_once()
        selected.assert_called_once()
        self.assertTrue(service._session(view.session_id).native_editor_session_ready)
        self.assertEqual("replace", selected.call_args.kwargs["operation"])
        self.assertEqual(
            {"vertices_by_submesh": {0: {0}}, "edges_by_submesh": {}, "faces_by_submesh": {0: {1}}},
            selected.call_args.args[1],
        )
        self.assertEqual(3.0, result.metrics["cpp_ms"])
        self.assertEqual(2.0, result.metrics["editor_open_cpp_ms"])
        self.assertEqual(3.0, result.metrics["editor_select_cpp_ms"])
        self.assertGreaterEqual(result.metrics["editor_open_roundtrip_ms"], 0.0)
        self.assertGreaterEqual(result.metrics["editor_select_roundtrip_ms"], 0.0)

    def test_select_uses_resident_native_session_when_mesh_dirty(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-native-dirty", mode="edit")
        session = service._session(view.session_id)
        session.native_editor_session_ready = True
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((8, 6),)

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty mesh hydrated")),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", side_effect=AssertionError("resident session reopened")),
            patch(
                "cdmw.services.mesh_service.select_native_mesh_editor_session",
                return_value={
                    "metrics": {"cpp_ms": 4.0},
                    "submeshes": [{"index": 0, "selected_vertex_start": 0, "selected_vertex_count": 2}],
                    "source_indices": [],
                },
            ) as selected,
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})),
            )

        self.assertTrue(result.ok)
        selected.assert_called_once()
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual({0: {0, 1}}, service.session_view(view.session_id).selection.vertex_map())

    def test_topology_edit_prunes_deleted_face_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="topology-selection-prune", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (1,)})),
        )
        deleted = service.apply_command(view.session_id, MeshEditCommand("delete"))

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertTrue(service.session_view(view.session_id).selection.is_empty())

    def test_undo_prunes_selection_referencing_removed_topology(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-selection-prune", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
        )
        view_after_duplicate = service.session_view(view.session_id)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
        )
        selected = service.session_view(view.session_id).selection

        undo = service.undo(view.session_id)
        view_after_undo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual(2, view_after_duplicate.submesh_count)
        self.assertEqual((1,), selected.source_indices)
        self.assertTrue(undo.ok)
        self.assertEqual(1, view_after_undo.submesh_count)
        self.assertEqual(1, view_after_undo.redo_count)
        self.assertTrue(view_after_undo.selection.is_empty())

    def test_undo_redo_restore_selection_context_snapshots(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-selection-context", mode="edit")
        original_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=original_selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate"))
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
        )
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertTrue(undo.ok)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertEqual((), after_undo.selection.source_indices)
        self.assertTrue(redo.ok)
        self.assertEqual({1: {0}}, after_redo.selection.face_map())
        self.assertEqual((1,), after_redo.selection.source_indices)

    def test_undo_redo_restore_mode_before_command_mode_switch(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-mode-context", mode="object")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate", mode="edit"))
        after_duplicate = service.session_view(view.session_id)
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertEqual("edit", after_duplicate.mode)
        self.assertTrue(undo.ok)
        self.assertEqual("object", after_undo.mode)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertTrue(redo.ok)
        self.assertEqual("edit", after_redo.mode)
        self.assertEqual({0: {0}}, after_redo.selection.face_map())

    def test_no_history_transform_updates_revision_without_undo_snapshot_and_clears_redo(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="live", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        service.apply_command(
            view.session_id,
            MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 1.0)}),
        )
        self.assertEqual(1, service.session_view(view.session_id).undo_count)
        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual(1, service.session_view(view.session_id).redo_count)

        live = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.0, 0.0, 0.25), "record_history": "false"},
            ),
        )

        state = service.session_view(view.session_id)
        self.assertTrue(live.ok)
        self.assertEqual(3, state.revision)
        self.assertEqual(0, state.undo_count)
        self.assertEqual(0, state.redo_count)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual("noop", service.undo(view.session_id).status)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_native_live_deformation_history_uses_sparse_vertex_delta(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-sparse-history", mode="object")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
        history_attr = "cdmw_native_mesh_history_vertex_delta"

        def native_live_edit(mesh: ParsedMesh, command: MeshEditCommand, _selection: MeshEditSelection) -> tuple[set[int], dict[int, set[int]]]:
            self.assertTrue(command.params.get("_require_native_history_delta"))
            submesh = mesh.submeshes[0]
            before = submesh.vertices[0]
            vertices = list(submesh.vertices)
            vertices[0] = (before[0], before[1], before[2] + 0.5)
            submesh.vertices = vertices
            setattr(
                submesh,
                history_attr,
                {
                    "source_submesh_index": 0,
                    "vertex_indices": (0,),
                    "before_positions": (before,),
                },
            )
            return {0}, {0: {0}}

        with (
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=native_live_edit),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            moved = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", mode="edit", selection=selection, params={"translate": (0.0, 0.0, 0.5)}),
            )
            after_move_mode = service.session_view(view.session_id).mode
            undo = service.undo(view.session_id)
            after_undo_vertex = service.working_mesh(view.session_id).submeshes[0].vertices[0]
            after_undo_mode = service.session_view(view.session_id).mode
            redo = service.redo(view.session_id)
            after_redo_mode = service.session_view(view.session_id).mode

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(moved.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertEqual(((0, range(0, 1)),), undo.changed_vertices_by_submesh)
        self.assertEqual(((0, range(0, 1)),), redo.changed_vertices_by_submesh)
        self.assertEqual("edit", after_move_mode)
        self.assertEqual("object", after_undo_mode)
        self.assertEqual("edit", after_redo_mode)
        self.assertEqual((0.0, 0.0, 0.0), after_undo_vertex)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])
        self.assertEqual(1, service.session_view(view.session_id).undo_count)
        self.assertEqual(0, service.session_view(view.session_id).redo_count)

    def test_native_live_deformation_history_uses_sparse_vertex_delta_with_stop_event(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-sparse-history-stop-event", mode="object")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
        stop_event = threading.Event()
        history_attr = "cdmw_native_mesh_history_vertex_delta"

        def native_live_edit(mesh: ParsedMesh, command: MeshEditCommand, _selection: MeshEditSelection) -> tuple[set[int], dict[int, set[int]]]:
            self.assertTrue(command.params.get("_require_native_history_delta"))
            self.assertIs(stop_event, command.params.get("stop_event"))
            submesh = mesh.submeshes[0]
            before = submesh.vertices[0]
            vertices = list(submesh.vertices)
            vertices[0] = (before[0], before[1], before[2] + 0.5)
            submesh.vertices = vertices
            setattr(
                submesh,
                history_attr,
                {
                    "source_submesh_index": 0,
                    "vertex_indices": (0,),
                    "before_positions": (before,),
                },
            )
            return {0}, {0: {0}}

        with (
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=native_live_edit),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            moved = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "transform",
                    mode="edit",
                    selection=selection,
                    params={"translate": (0.0, 0.0, 0.5), "stop_event": stop_event},
                ),
            )
            undo = service.undo(view.session_id)

        self.assertTrue(moved.ok)
        self.assertTrue(undo.ok)
        self.assertEqual(((0, range(0, 1)),), undo.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_native_live_history_unavailable_fallback_uses_native_snapshot_before_clone(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-history-fallback", mode="object")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with (
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("legacy geometry fallback")),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("snapshot fallback")),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            moved = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", mode="edit", selection=selection, params={"translate": (0.0, 0.0, 0.5)}),
            )

        snapshot = service._sessions[view.session_id].undo_stack[0]
        self.assertTrue(moved.ok)
        self.assertIsNone(snapshot.mesh)
        self.assertIsNone(snapshot.native_submesh_snapshot)
        self.assertEqual("object", snapshot.mode)
        self.assertEqual((0.0, 0.0, 0.5), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_native_history_snapshot_blocks_python_clone_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-history-snapshot-blocked", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
        fallback_events: list[tuple[str, str, dict[str, object]]] = []

        def record_fallback(operation: str, reason: str, **details: object) -> None:
            fallback_events.append((operation, reason, details))

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("snapshot fallback")),
            patch("cdmw.services.mesh_service.record_native_mesh_core_fallback", side_effect=record_fallback),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("legacy geometry fallback")),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone fallback")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("delete", mode="edit", selection=selection),
            )

        self.assertTrue(result.ok)
        self.assertEqual(1, service.session_view(view.session_id).undo_count)
        self.assertEqual([], fallback_events)

    def test_native_live_deformation_history_restore_uses_native_sparse_restore(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-sparse-history-restore", mode="object")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with (
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("legacy geometry fallback")),
            patch("cdmw.services.mesh_service.apply_native_mesh_sparse_vertex_restore", side_effect=AssertionError("python sparse restore fallback")),
            patch("cdmw.services.mesh_service.dispose_native_mesh_sparse_vertex_snapshot", side_effect=AssertionError("python sparse dispose")),
            patch("cdmw.services.mesh_service._current_vertex_position_deltas", side_effect=AssertionError("python current capture")),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            moved = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", mode="edit", selection=selection, params={"translate": (0.0, 0.0, 0.5)}),
            )
            undo = service.undo(view.session_id)
            after_undo_vertex = service.working_mesh(view.session_id).submeshes[0].vertices[0]
            redo = service.redo(view.session_id)

        self.assertTrue(moved.ok)
        self.assertTrue(undo.ok)
        self.assertTrue(redo.ok)
        self.assertEqual((0.0, 0.0, 0.0), after_undo_vertex)
        self.assertEqual((0.0, 0.0, 0.5), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_native_sparse_history_restore_blocks_python_fallback(self) -> None:
        from cdmw.services import mesh_service as mesh_service_module

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-history-restore-blocked", mode="object")
        session = service._sessions[view.session_id]
        vertices = list(session.working_mesh.submeshes[0].vertices)
        vertices[0] = (0.0, 0.0, 1.0)
        session.working_mesh.submeshes[0].vertices = vertices
        session.undo_stack.append(
            mesh_service_module._MeshHistorySnapshot(
                mesh=None,
                mode="object",
                selection=MeshEditSelection(),
                vertex_position_deltas=(
                    mesh_service_module._MeshVertexPositionDelta(
                        submesh_index=0,
                        vertex_indices=(0,),
                        positions=((0.0, 0.0, 0.0),),
                        native_sparse_snapshot_id="native-history-missing",
                    ),
                ),
            )
        )
        fallback_events: list[tuple[str, str, dict[str, object]]] = []

        def record_fallback(operation: str, reason: str, **details: object) -> None:
            fallback_events.append((operation, reason, details))

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.apply_native_mesh_sparse_vertex_restore", return_value=None),
            patch("cdmw.services.mesh_service.record_native_mesh_core_fallback", side_effect=record_fallback),
            patch("cdmw.services.mesh_service._current_vertex_position_deltas", side_effect=AssertionError("python history restore fallback")),
            patch("cdmw.services.mesh_service.recompute_mesh_normals", side_effect=AssertionError("python normal fallback")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python fallback was blocked"):
                service.undo(view.session_id)

        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual("history.sparse_restore.blocked", fallback_events[0][0])

    def test_live_deformation_actions_skip_topology_signature_scan(self) -> None:
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="no-topology-signature-transform", mode="edit")
        brush_view = service.open_edit_session(_quad_mesh(), session_id="no-topology-signature-brush", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with patch("cdmw.services.mesh_service._mesh_structure_signature", side_effect=AssertionError("topology scan")):
            transform = service.apply_command(
                transform_view.session_id,
                MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.25), "record_history": False}),
            )
            brush = service.apply_command(
                brush_view.session_id,
                MeshEditCommand(
                    "brush",
                    selection=selection,
                    mode="sculpt",
                    params={
                        "tool": "grab",
                        "center": (0.0, 0.0, 0.0),
                        "radius": 2.0,
                        "strength": 1.0,
                        "delta": (0.0, 0.0, 0.25),
                        "record_history": False,
                    },
                ),
            )

        self.assertTrue(transform.ok)
        self.assertFalse(transform.topology_changed)
        self.assertTrue(brush.ok)
        self.assertFalse(brush.topology_changed)

    def test_explicit_live_deformation_selection_skips_session_selection_prune(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="explicit-live-selection-prune", mode="edit")
        session = service._session(view.session_id)
        session.selection = MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(range(100_000))})
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        def native_transform(mesh: ParsedMesh, vertices_by_submesh: object, **_params: object) -> dict[int, set[int]]:
            self.assertEqual({0: {0}}, vertices_by_submesh)
            submesh = mesh.submeshes[0]
            vertices = list(submesh.vertices)
            vertices[0] = (0.0, 0.0, 0.25)
            submesh.vertices = vertices
            return {0: {0}}

        with (
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("session prune")),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform", side_effect=AssertionError("legacy transform helper")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.25), "record_history": False}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(1, session.revision)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_implicit_native_selection_skips_python_prune_when_mesh_is_dirty(self) -> None:
        from cdmw.services import mesh_service as mesh_service_module

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="implicit-native-selection-dirty", mode="edit")
        session = service._session(view.session_id)
        session.selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
        session.native_editor_session_ready = True
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)
        captured: dict[str, object] = {}

        def native_apply(_session: object, _command: object, selection: MeshEditSelection) -> object:
            captured["selection"] = selection
            return mesh_service_module._NativeEditorApplyResult(
                affected={0},
                changed={0: {0}},
                metrics={"cpp_ms": 1.0},
                submesh_counts=((4, 2),),
            )

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service._sync_native_editor_session_to_working_mesh", side_effect=AssertionError("dirty mesh hydrated")),
            patch("cdmw.services.mesh_service._prune_selection_to_mesh", side_effect=AssertionError("python selection prune")),
            patch("cdmw.services.mesh_service._apply_native_editor_session_geometry_action", side_effect=native_apply),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", params={"translate": (0.0, 0.0, 0.25), "record_history": False}),
            )

        self.assertTrue(result.ok)
        self.assertIs(captured["selection"], session.selection)
        self.assertTrue(session.native_editor_mesh_dirty)
        self.assertEqual(((0, (0,)),), result.changed_vertices_by_submesh)

    def test_transform_selection_domains_go_native_before_python_vertex_expansion(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-transform-selection-domain", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        with (
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python vertex expansion")),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", side_effect=AssertionError("legacy transform helper reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.25), "record_history": False}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_brush_selection_domains_go_native_before_python_vertex_expansion(self) -> None:
        from cdmw.services import mesh_service as mesh_service_module

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-brush-selection-domain", mode="sculpt")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})
        captured: dict[str, object] = {}

        def native_apply(_session: object, _command: object, forwarded_selection: MeshEditSelection) -> object:
            captured["selection"] = forwarded_selection
            return mesh_service_module._NativeEditorApplyResult(
                affected={0},
                changed={0: (0, 1)},
                metrics={"cpp_ms": 1.0},
                submesh_counts=((4, 2),),
            )

        with (
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python vertex expansion")),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_selection", side_effect=AssertionError("legacy brush helper")),
            patch("cdmw.services.mesh_service._apply_native_editor_session_geometry_action", side_effect=native_apply),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "brush",
                    selection=selection,
                    mode="sculpt",
                    params={
                        "tool": "grab",
                        "center": (0.0, 0.0, 0.0),
                        "radius": 2.0,
                        "strength": 1.0,
                        "delta": (0.0, 0.0, 0.25),
                        "record_history": False,
                    },
                ),
            )

        self.assertTrue(result.ok)
        self.assertIs(captured["selection"], selection)
        self.assertEqual(((0, (0, 1)),), result.changed_vertices_by_submesh)

    def test_identity_transform_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0), "rotate": (0.0, 0.0, 0.0)}),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_transform_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("transform must use resident native editor session"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 2.0)}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 2.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)

    def test_brush_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-brush", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_selection", side_effect=AssertionError("legacy brush helper")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("python geometry fallback")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("brush", selection=selection, mode="sculpt", params={"tool": "grab", "drag_delta": (0.0, 0.0, 0.5)}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.5), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)

    def test_large_required_edit_tools_use_resident_native_without_python_fallback(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        cases = (
            ("transform", "edit", MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {"translate": (0.0, 0.0, 1.0)}),
            ("brush", "sculpt", MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {"tool": "grab", "drag_delta": (0.0, 0.0, 1.0)}),
            ("delete", "edit", MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), {}),
            ("subdivide", "edit", MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), {}),
            ("refine_smooth", "edit", MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), {}),
            ("split", "edit", MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), {}),
        )
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_binary_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_binary_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_delete", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_subdivide", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_split", return_value=None),
        ):
            for action, mode, selection, params in cases:
                with self.subTest(action=action):
                    service = MeshService()
                    view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id=f"large-{action}", mode=mode)
                    result = service.apply_command(
                        view.session_id,
                        MeshEditCommand(action, selection=selection, mode=mode, params={**params, "record_history": False}),
                    )
                    self.assertTrue(result.ok)
                    self.assertEqual((), result.diagnostics)
                    self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)
        fallback_counts = native_mesh_core_fallback_counts()
        self.assertEqual({}, fallback_counts)
        clear_native_mesh_core_fallback_counts()

    def test_large_selection_domains_use_resident_native_without_python_full_vertex_expansion(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        cases = (
            (
                "source-transform",
                "transform",
                "edit",
                MeshEditSelection.from_maps(source_indices=(0,)),
                {"translate": (0.0, 0.0, 1.0)},
            ),
            (
                "edge-transform",
                "transform",
                "edit",
                MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                {"translate": (0.0, 0.0, 1.0)},
            ),
            (
                "source-brush",
                "brush",
                "sculpt",
                MeshEditSelection.from_maps(source_indices=(0,)),
                {"tool": "grab", "drag_delta": (0.0, 0.0, 1.0)},
            ),
            (
                "face-brush",
                "brush",
                "sculpt",
                MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                {"tool": "grab", "drag_delta": (0.0, 0.0, 1.0)},
            ),
        )
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_binary_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform", side_effect=AssertionError("native explicit transform should not need Python-expanded source vertices")),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_binary_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush", side_effect=AssertionError("native explicit brush should not need Python-expanded source vertices")),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python full-submesh vertex expansion reached")),
        ):
            for case_name, action, mode, selection, params in cases:
                with self.subTest(case=case_name):
                    service = MeshService()
                    view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id=f"large-{case_name}", mode=mode)
                    result = service.apply_command(
                        view.session_id,
                        MeshEditCommand(
                            action,
                            selection=selection,
                            mode=mode,
                            params={**params, "record_history": False},
                        ),
                    )
                    self.assertTrue(result.ok)
                    self.assertEqual((), result.diagnostics)
                    self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)
        fallback_counts = native_mesh_core_fallback_counts()
        self.assertEqual({}, fallback_counts)
        clear_native_mesh_core_fallback_counts()

    def test_large_topology_copy_tools_use_resident_native_before_python_face_expansion(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        cases = ("duplicate", "separate")
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_duplicate", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_separate", return_value=None),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python face expansion reached")),
        ):
            for action in cases:
                with self.subTest(action=action):
                    service = MeshService()
                    view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id=f"large-{action}-copy", mode="edit")
                    result = service.apply_command(
                        view.session_id,
                        MeshEditCommand(
                            action,
                            selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                            mode="edit",
                            params={"record_history": False},
                        ),
                    )
                    self.assertTrue(result.ok)
                    self.assertEqual((), result.diagnostics)
                    self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)
        self.assertEqual({}, native_mesh_core_fallback_counts())
        clear_native_mesh_core_fallback_counts()

    def test_large_copy_normals_blocks_before_python_full_vertex_expansion(self) -> None:
        from cdmw.modding import mesh_edit_ops
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        cases = (
            ("source", MeshEditSelection.from_maps(source_indices=(0,))),
            ("vertex", MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
            ("edge", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
            ("face", MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
        )
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_copy_normals", return_value=None),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python normal-copy vertex expansion reached")),
        ):
            for case_name, selection in cases:
                with self.subTest(case=case_name):
                    mesh = _large_mesh_for_native_fallback_guard()
                    affected, changed = mesh_edit_ops._copy_normals(
                        mesh,
                        selection,
                        {"source_mesh": mesh},
                    )
                    self.assertEqual(set(), affected)
                    self.assertEqual({}, changed)
        self.assertEqual(len(cases), native_mesh_core_fallback_counts()["normals.copy.blocked"])
        clear_native_mesh_core_fallback_counts()

    def test_copy_normals_edge_selection_forwards_native_domains_before_python_expansion(self) -> None:
        from cdmw.modding import mesh_edit_ops

        mesh = _quad_mesh()
        source_mesh = _quad_mesh()
        calls: list[dict[str, object]] = []

        def native_copy_normals(target_mesh: ParsedMesh, source: ParsedMesh, vertices_by_submesh: object, **params: object) -> dict[int, set[int]]:
            calls.append({"vertices_by_submesh": vertices_by_submesh, **params})
            target_mesh.submeshes[0].normals[0] = (0.0, 0.0, 1.0)
            target_mesh.submeshes[0].normals[1] = (0.0, 0.0, 1.0)
            self.assertIs(source, source_mesh)
            return {0: {0, 1}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_copy_normals", side_effect=native_copy_normals),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python normal-copy vertex expansion reached")),
        ):
            affected, changed = mesh_edit_ops._copy_normals(
                mesh,
                MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                {"source_mesh": source_mesh},
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: {0, 1}}, changed)
        self.assertEqual({}, calls[0]["vertices_by_submesh"])
        self.assertEqual({0: {(0, 1)}}, calls[0]["selected_edges_by_submesh"])
        self.assertEqual({}, calls[0]["selected_faces_by_submesh"])
        self.assertEqual((), calls[0]["source_indices"])

    def test_native_mesh_core_copy_normals_expands_edge_domain_in_cpp(self) -> None:
        from cdmw.modding import mesh_native_core

        if mesh_native_core.find_native_mesh_core_binary() is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        source_mesh = _quad_mesh()
        mesh.submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        source_mesh.submeshes[0].normals = [
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
        ]

        changed = mesh_native_core.apply_native_mesh_copy_normals(
            mesh,
            source_mesh,
            {},
            selected_edges_by_submesh={0: {(0, 1)}},
        )

        self.assertEqual({0, 1}, set(changed[0]))  # type: ignore[index]
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].normals[0])
        self.assertEqual((0.0, 1.0, 0.0), mesh.submeshes[0].normals[1])
        self.assertEqual((0.0, 0.0, -1.0), mesh.submeshes[0].normals[2])

    def test_large_sharpen_normals_blocks_before_python_full_face_expansion(self) -> None:
        from cdmw.modding import mesh_edit_ops
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        mesh = _large_mesh_for_native_fallback_guard()
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_sharpen_normals", return_value=None),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python normal-sharpen face expansion reached")),
        ):
            affected, changed = mesh_edit_ops._sharpen_normals(
                mesh,
                MeshEditSelection.from_maps(source_indices=(0,)),
            )

        self.assertEqual(set(), affected)
        self.assertEqual({}, changed)
        self.assertEqual(1, native_mesh_core_fallback_counts()["normals.sharpen.blocked"])
        clear_native_mesh_core_fallback_counts()

    def test_large_optional_cleanup_tools_use_resident_native_editor_without_python_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        cases = (
            ("remove_doubles", "edit", {"threshold": 0.001}),
            ("delete_loose_vertices", "edit", {}),
        )
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("cleanup legacy geometry reached"),
        ):
            for action, mode, params in cases:
                with self.subTest(action=action):
                    service = MeshService()
                    view = service.open_edit_session(
                        _large_mesh_for_native_fallback_guard(),
                        session_id=f"large-{action}",
                        mode=mode,
                    )
                    result = service.apply_command(
                        view.session_id,
                        MeshEditCommand(
                            action,
                            mode=mode,
                            selection=MeshEditSelection.from_maps(source_indices=(0,)),
                            params={**params, "record_history": False},
                        ),
                    )
                    mesh = service.working_mesh(view.session_id)
                    self.assertTrue(result.ok)
                    self.assertEqual((0,), result.affected_submesh_indices)
                    self.assertEqual((), result.changed_vertices_by_submesh)
                    self.assertEqual((), result.diagnostics)
                    self.assertEqual(3, mesh.submeshes[0].vertex_count)
                    self.assertEqual(1, mesh.submeshes[0].face_count)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_large_native_transform_blocks_python_normal_fallback(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        service = MeshService()
        view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id="large-transform-normals", mode="edit")
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_edit_ops.native_mesh_core_available", return_value=True),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_binary_selection", return_value=None),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", return_value={0: {0}}),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_recalculate_normals", return_value=None),
            patch(
                "cdmw.modding.mesh_edit_ops.recompute_submesh_normals",
                side_effect=AssertionError("python normal fallback"),
            ),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "transform",
                    selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
                    mode="edit",
                    params={"translate": (0.0, 0.0, 1.0), "record_history": False},
                ),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual({}, native_mesh_core_fallback_counts())
        clear_native_mesh_core_fallback_counts()

    def test_selection_prune_blocks_python_fallback_when_native_available(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="strict-selection-prune", mode="edit")
        clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.services.mesh_service_selection.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"metrics": {"cpp_ms": 1.0}}),
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value=None),
            patch("cdmw.services.mesh_service_selection.prune_native_mesh_selection", side_effect=AssertionError("obsolete prune fallback")),
            patch(
                "cdmw.services.mesh_service_selection._valid_selected_edges_for_submesh",
                side_effect=AssertionError("python selection prune fallback"),
            ),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection.from_maps(
                        vertices_by_submesh={0: (0,)},
                        edges_by_submesh={0: ((0, 1),)},
                        faces_by_submesh={0: (0,)},
                        source_indices=(0,),
                    ),
                ),
            )

        session = service._session(view.session_id)
        self.assertFalse(result.ok)
        self.assertEqual("error", result.status)
        self.assertEqual(1, len(result.diagnostics))
        self.assertIn("Python fallback is disabled", result.diagnostics[0])
        self.assertEqual({}, session.selection.vertex_map())
        self.assertEqual({}, session.selection.edge_map())
        self.assertEqual({}, session.selection.face_map())
        self.assertEqual((), session.selection.source_indices)
        self.assertEqual({}, native_mesh_core_fallback_counts())
        clear_native_mesh_core_fallback_counts()

    def test_delete_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-delete", mode="edit")

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_delete", side_effect=AssertionError("legacy delete helper")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("python geometry fallback")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("delete", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (1,)}), mode="edit"),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual([(0, 1, 2)], service.working_mesh(view.session_id).submeshes[0].faces)
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)

    def test_subdivide_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-subdivide", mode="edit")

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_subdivide", side_effect=AssertionError("legacy subdivide helper")):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode="edit"),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual({0, 1, 2, 4, 5, 6}, _changed_vertices_as_set(result))
        self.assertEqual(7, service.working_mesh(view.session_id).submeshes[0].vertex_count)

    def test_split_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-split", mode="edit")

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_split", side_effect=AssertionError("legacy split helper")):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), mode="edit"),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual({4, 5}, _changed_vertices_as_set(result))
        self.assertEqual(6, service.working_mesh(view.session_id).submeshes[0].vertex_count)

    def test_transform_requires_explicit_selection_or_source_target(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-transform-target", mode="edit")

        empty = service.apply_command(
            empty_view.session_id,
            MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}),
        )

        empty_mesh = service.working_mesh(empty_view.session_id)
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual((), empty.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), empty_mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.0), empty_mesh.submeshes[0].vertices[3])

        source_view = service.open_edit_session(_quad_mesh(), session_id="source-transform-target", mode="edit")
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"translate": (0.0, 0.0, 1.0)},
            ),
        )

        source_mesh = service.working_mesh(source_view.session_id)
        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        self.assertEqual(((0, range(0, 4)),), source.changed_vertices_by_submesh)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)
        self.assertEqual((0.0, 0.0, 1.0), source_mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 1.0), source_mesh.submeshes[0].vertices[3])

    def test_stale_edge_selection_does_not_partially_edit_valid_endpoint(self) -> None:
        stale_edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-transform", mode="edit")

        moved = service.apply_command(
            transform_view.session_id,
            MeshEditCommand("transform", selection=stale_edge, params={"translate": (0.0, 0.0, 1.0)}),
        )

        transform_submesh = service.working_mesh(transform_view.session_id).submeshes[0]
        self.assertTrue(moved.ok)
        self.assertEqual((), moved.affected_submesh_indices)
        self.assertEqual((0.0, 0.0, 0.0), transform_submesh.vertices[0])
        self.assertEqual(0, service.session_view(transform_view.session_id).revision)

        uv_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-uv", mode="edit")
        uv = service.apply_command(
            uv_view.session_id,
            MeshEditCommand("uv_transform", selection=stale_edge, params={"offset": (0.25, 0.0)}),
        )

        uv_submesh = service.working_mesh(uv_view.session_id).submeshes[0]
        self.assertTrue(uv.ok)
        self.assertEqual((), uv.affected_submesh_indices)
        self.assertEqual((0.0, 0.0), uv_submesh.uvs[0])
        self.assertEqual(0, service.session_view(uv_view.session_id).revision)

    def test_non_existing_edge_selection_does_not_edit_mesh_with_faces(self) -> None:
        non_edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)})
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-transform", mode="edit")

        moved = service.apply_command(
            transform_view.session_id,
            MeshEditCommand("transform", selection=non_edge, params={"translate": (0.0, 0.0, 1.0)}),
        )

        transform_submesh = service.working_mesh(transform_view.session_id).submeshes[0]
        self.assertTrue(moved.ok)
        self.assertEqual((), moved.affected_submesh_indices)
        self.assertEqual((0.0, 0.0, 0.0), transform_submesh.vertices[0])
        self.assertEqual((1.0, 1.0, 0.0), transform_submesh.vertices[3])
        self.assertEqual(0, service.session_view(transform_view.session_id).revision)

        uv_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-uv", mode="edit")
        uv = service.apply_command(
            uv_view.session_id,
            MeshEditCommand("uv_transform", selection=non_edge, params={"offset": (0.25, 0.0)}),
        )

        uv_submesh = service.working_mesh(uv_view.session_id).submeshes[0]
        self.assertTrue(uv.ok)
        self.assertEqual((), uv.affected_submesh_indices)
        self.assertEqual((0.0, 0.0), uv_submesh.uvs[0])
        self.assertEqual(0, service.session_view(uv_view.session_id).revision)

        extrude_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-extrude", mode="edit")
        extruded = service.apply_command(
            extrude_view.session_id,
            MeshEditCommand("extrude", selection=non_edge, params={"offset": (0.0, 0.0, 0.25)}),
        )

        extrude_submesh = service.working_mesh(extrude_view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertFalse(extruded.topology_changed)
        self.assertEqual((), extruded.affected_submesh_indices)
        self.assertEqual(4, extrude_submesh.vertex_count)
        self.assertEqual(2, extrude_submesh.face_count)
        self.assertEqual(0, service.session_view(extrude_view.session_id).revision)

    def test_malformed_faces_are_ignored_by_shared_face_targeting(self) -> None:
        service = MeshService()
        malformed = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
        malformed_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-explicit", mode="edit")

        malformed_result = service.apply_command(malformed_view.session_id, MeshEditCommand("duplicate", selection=malformed))

        self.assertTrue(malformed_result.ok)
        self.assertFalse(malformed_result.topology_changed)
        self.assertEqual((), malformed_result.affected_submesh_indices)
        self.assertEqual(1, service.session_view(malformed_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(malformed_view.session_id).revision)

        edge_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-edge", mode="edit")
        edge_result = service.apply_command(
            edge_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        edge_mesh = service.working_mesh(edge_view.session_id)
        self.assertTrue(edge_result.ok)
        self.assertTrue(edge_result.topology_changed)
        self.assertEqual((1,), edge_result.affected_submesh_indices)
        self.assertEqual([(0, 1, 2)], edge_mesh.submeshes[1].faces)

        vertex_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-vertex", mode="edit")
        vertex_result = service.apply_command(
            vertex_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
        )

        vertex_mesh = service.working_mesh(vertex_view.session_id)
        self.assertTrue(vertex_result.ok)
        self.assertTrue(vertex_result.topology_changed)
        self.assertEqual((1,), vertex_result.affected_submesh_indices)
        self.assertEqual([(0, 1, 2)], vertex_mesh.submeshes[1].faces)

    def test_malformed_faces_do_not_crash_face_scanning_edit_ops(self) -> None:
        cases = (
            ("extrude", MeshEditSelection.from_maps(faces_by_submesh={0: (1,)}), {"offset": (0.0, 0.0, 0.25)}),
            ("inset", MeshEditSelection.from_maps(faces_by_submesh={0: (1,)}), {"amount": 0.25}),
            ("loop_cut", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), {}),
            ("edge_split", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), {}),
            ("fill", MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2, 3)}), {}),
            ("bridge", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))}), {}),
            ("merge", MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)}), {}),
        )
        for action, selection, params in cases:
            with self.subTest(action=action):
                service = MeshService()
                view = service.open_edit_session(_malformed_face_mesh(), session_id=f"malformed-face-{action}", mode="edit")

                result = service.apply_command(view.session_id, MeshEditCommand(action, selection=selection, params=params))

                self.assertTrue(result.ok)
                if result.affected_submesh_indices or result.topology_changed:
                    for submesh in service.working_mesh(view.session_id).submeshes:
                        for face in submesh.faces:
                            self.assertEqual(3, len(face))
                            self.assertTrue(all(isinstance(index, int) for index in face))

    def test_mirror_aware_identity_transform_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-mirror-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (0.0, 0.0, 0.0),
                    "mirror_x": True,
                    "mirror_pairs_by_submesh": {0: {0: 1, 1: 0}},
                },
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_empty_selection_brush_uses_radius_instead_of_whole_submesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="brush-radius", mode="sculpt")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                params={
                    "tool": "grab",
                    "center": (0.0, 0.0, 0.0),
                    "radius": 0.1,
                    "strength": 1.0,
                    "delta": (0.0, 0.0, 0.25),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_smooth_brush_relaxes_selected_spike_without_topology_change(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_spike_mesh(), session_id="smooth-brush-spike", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={
                    "tool": "smooth",
                    "center": (0.0, 0.0, 1.0),
                    "radius": 0.25,
                    "strength": 0.5,
                    "iterations": 3,
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertFalse(result.topology_changed)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(0.125, mesh.submeshes[0].vertices[0][2], places=6)
        self.assertEqual(5, mesh.submeshes[0].vertex_count)
        self.assertEqual(4, mesh.submeshes[0].face_count)

    def test_refine_smooth_adds_vertices_and_relaxes_selected_spike(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_spike_mesh(), session_id="refine-smooth-spike", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "refine_smooth",
                selection=selection,
                params={"smooth_strength": 0.5, "smooth_iterations": 2},
            ),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        changed = dict(result.changed_vertices_by_submesh)[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertGreater(submesh.vertex_count, 5)
        self.assertGreater(submesh.face_count, 4)
        self.assertLess(submesh.vertices[0][2], 1.0)
        self.assertIn(0, changed)
        self.assertTrue(any(index >= 5 for index in changed))

    def test_identity_brush_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-brush", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.0)},
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_brush_rejects_non_finite_numeric_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="brush-non-finite", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={
                    "tool": "grab",
                    "center": (float("inf"), 0.0, 0.0),
                    "radius": float("inf"),
                    "strength": float("nan"),
                    "delta": (0.0, 0.0, float("inf")),
                    "amount": float("nan"),
                    "iterations": float("inf"),
                    "vertex_weights": {0: float("nan"), 1: float("inf")},
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))

    def test_mode_specific_commands_noop_until_mode_matches(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mode-gates", mode="object")
        face_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
        vertex_selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        blocked_topology = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=face_selection, params={"offset": (0.0, 0.0, 0.25)}),
        )
        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=face_selection, mode="edit", params={"offset": (0.0, 0.0, 0.25)}),
        )
        blocked_brush = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=vertex_selection,
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.25)},
            ),
        )
        brushed = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=vertex_selection,
                mode="sculpt",
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.25)},
            ),
        )

        self.assertEqual("noop", blocked_topology.status)
        self.assertIn("requires edit mode", blocked_topology.diagnostics[0])
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual("noop", blocked_brush.status)
        self.assertIn("requires sculpt mode", blocked_brush.diagnostics[0])
        self.assertTrue(brushed.ok)
        self.assertEqual("sculpt", service.session_view(view.session_id).mode)
        self.assertEqual(((0, range(0, 1)),), brushed.changed_vertices_by_submesh)

    def test_material_commands_require_edit_mode(self) -> None:
        service = MeshService()
        assign_view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-assign-mode-gate", mode="object")
        target = MeshEditSelection.from_maps(source_indices=(0,))

        blocked_assign = service.apply_command(
            assign_view.session_id,
            MeshEditCommand("material_assign", selection=target, params={"material": "blocked", "texture": "blocked.dds"}),
        )
        assigned = service.apply_command(
            assign_view.session_id,
            MeshEditCommand("material_assign", selection=target, mode="edit", params={"material": "edited", "texture": "edited.dds"}),
        )

        assign_mesh = service.working_mesh(assign_view.session_id)
        self.assertEqual("noop", blocked_assign.status)
        self.assertIn("requires edit mode", blocked_assign.diagnostics[0])
        self.assertTrue(assigned.ok)
        self.assertEqual("edited", assign_mesh.submeshes[0].material)
        self.assertEqual("edited.dds", assign_mesh.submeshes[0].texture)

        copy_view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy-mode-gate", mode="object")
        blocked_copy = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )
        copied = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), mode="edit", params={"source_submesh_index": 0}),
        )

        copy_mesh = service.working_mesh(copy_view.session_id)
        self.assertEqual("noop", blocked_copy.status)
        self.assertIn("requires edit mode", blocked_copy.diagnostics[0])
        self.assertTrue(copied.ok)
        self.assertEqual("mat_a", copy_mesh.submeshes[1].material)
        self.assertEqual("a.dds", copy_mesh.submeshes[1].texture)

    def test_extrude_reuses_region_vertices_and_skips_internal_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="extrude-region", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=selection, params={"offset": (0.0, 0.0, 0.5)}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual(((0, range(4, 8)),), extruded.changed_vertices_by_submesh)
        self.assertEqual(8, submesh.vertex_count)
        self.assertEqual(12, submesh.face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], submesh.faces[2:4])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in submesh.faces[4:]))

    def test_extrude_can_pull_selected_loose_edge_into_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="extrude-loose-edge", mode="edit")

        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "extrude",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                params={"offset": (0.0, 0.0, 0.5)},
            ),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual(((0, range(4, 6)),), extruded.changed_vertices_by_submesh)
        self.assertEqual(6, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual((0.0, 0.0, 0.5), submesh.vertices[4])
        self.assertEqual((1.0, 0.0, 0.5), submesh.vertices[5])
        self.assertEqual((0.0, 0.0), submesh.uvs[4])
        self.assertEqual((1.0, 0.0), submesh.uvs[5])
        self.assertEqual([(0, 1, 5), (0, 5, 4)], submesh.faces)

    def test_extrude_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-extrude", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})
        calls: list[tuple[dict[int, set[int]], tuple[float, float, float], bool]] = []

        def native_extrude(
            target_mesh: ParsedMesh,
            selected_faces_by_submesh: Mapping[int, set[int]],
            _selected_vertices_by_submesh: Mapping[int, set[int]] | None,
            params: Mapping[str, object],
            *,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> tuple[set[int], dict[int, set[int]]]:
            calls.append(
                (
                    {index: set(faces) for index, faces in selected_faces_by_submesh.items()},
                    tuple(float(value) for value in params["offset"]),  # type: ignore[index]
                    recompute_normals,
                )
            )
            target = target_mesh.submeshes[0]
            target.vertices = list(target.vertices) + [
                (0.0, 0.0, 0.5),
                (1.0, 0.0, 0.5),
                (0.0, 1.0, 0.5),
                (1.0, 1.0, 0.5),
            ]
            target.uvs = list(target.uvs) + list(target.uvs)
            target.normals = list(target.normals) + list(target.normals)
            target.faces = [(0, 1, 2), (1, 3, 2), (4, 5, 6), (5, 7, 6)]
            target.vertex_count = 8
            target.face_count = 4
            return {0}, {0: {4, 5, 6, 7}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_extrude", side_effect=AssertionError("legacy extrude helper")),
            patch("cdmw.modding.mesh_edit_ops._valid_face_items", side_effect=AssertionError("python extrude loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("extrude", selection=selection, params={"offset": (0.0, 0.0, 0.5)}),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(4, 8)),), result.changed_vertices_by_submesh)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(4, working.submeshes[0].vertex_count)
        self.assertEqual(8, service.working_mesh(view.session_id).submeshes[0].vertex_count)

    def test_inset_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-inset", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})
        calls: list[tuple[dict[int, set[int]], float, bool]] = []

        def native_inset(
            target_mesh: ParsedMesh,
            selected_faces_by_submesh: Mapping[int, set[int]],
            _selected_vertices_by_submesh: Mapping[int, set[int]] | None,
            params: Mapping[str, object],
            *,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> tuple[set[int], dict[int, set[int]]]:
            calls.append(
                (
                    {index: set(faces) for index, faces in selected_faces_by_submesh.items()},
                    float(params["amount"]),  # type: ignore[index]
                    recompute_normals,
                )
            )
            target = target_mesh.submeshes[0]
            target.vertices = list(target.vertices) + [
                (0.25, 0.25, 0.0),
                (0.75, 0.25, 0.0),
                (0.25, 0.75, 0.0),
                (0.75, 0.75, 0.0),
            ]
            target.uvs = list(target.uvs) + list(target.uvs)
            target.normals = list(target.normals) + list(target.normals)
            target.faces = [
                (4, 5, 6),
                (5, 7, 6),
                (0, 1, 5),
                (0, 5, 4),
                (1, 3, 7),
                (1, 7, 5),
                (3, 2, 6),
                (3, 6, 7),
                (2, 0, 4),
                (2, 4, 6),
            ]
            target.vertex_count = 8
            target.face_count = 10
            return {0}, {0: {4, 5, 6, 7}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_inset", side_effect=AssertionError("legacy inset helper")),
            patch("cdmw.modding.mesh_edit_ops._valid_face_items", side_effect=AssertionError("python inset loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("inset", selection=selection, params={"amount": 0.5}),
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(4, 8)),), result.changed_vertices_by_submesh)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(4, working.submeshes[0].vertex_count)
        self.assertEqual(8, service.working_mesh(view.session_id).submeshes[0].vertex_count)

    def test_inset_reuses_region_vertices_and_skips_internal_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="inset-region", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        inset = service.apply_command(
            view.session_id,
            MeshEditCommand("inset", selection=selection, params={"amount": 0.5}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(inset.ok)
        self.assertTrue(inset.topology_changed)
        self.assertEqual(((0, range(4, 8)),), inset.changed_vertices_by_submesh)
        self.assertEqual(8, submesh.vertex_count)
        self.assertEqual(10, submesh.face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], submesh.faces[:2])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in submesh.faces[2:]))

    def test_inset_zero_amount_noops_without_topology_or_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="inset-zero", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        inset = service.apply_command(
            view.session_id,
            MeshEditCommand("inset", selection=selection, params={"amount": 0.0}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(inset.ok)
        self.assertFalse(inset.topology_changed)
        self.assertEqual((), inset.affected_submesh_indices)
        self.assertEqual((), inset.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_topology_uv_material_and_normals_commands_are_service_callable(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="suite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))

        extrude = service.apply_command(view.session_id, MeshEditCommand("extrude", params={"offset": (0.0, 0.0, 0.5)}))
        self.assertTrue(extrude.ok)
        self.assertTrue(extrude.topology_changed)
        self.assertGreater(service.working_mesh(view.session_id).total_faces, 4)

        uv = service.apply_command(view.session_id, MeshEditCommand("uv_transform", params={"flip_u": True, "offset": (0.25, 0.0)}))
        self.assertTrue(uv.ok)
        changed_uv_vertices = dict(uv.changed_vertices_by_submesh)[0]
        self.assertTrue({0, 1, 2, 3}.issubset(changed_uv_vertices))

        material = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                params={
                    "material": "edited",
                    "texture": "edited.dds",
                    "material_authority_profile": "material_authority_detail_mask",
                    "source_material_name": "source_mat",
                    "target_material_slot_index": 3,
                    "source_texture_set_key": "source_mat",
                    "roughness": 0.35,
                    "metalness": 0.8,
                },
            ),
        )
        self.assertTrue(material.ok)
        edited_submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual("edited", edited_submesh.material)
        self.assertEqual("edited.dds", edited_submesh.texture)
        self.assertEqual("material_authority_detail_mask", getattr(edited_submesh, "cdmw_material_authority_profile"))
        self.assertEqual("true_source_authority_detail_mask", getattr(edited_submesh, "cdmw_material_authority_contract"))
        self.assertEqual("source_mat", getattr(edited_submesh, "cdmw_source_material_name"))
        self.assertEqual(3, getattr(edited_submesh, "cdmw_target_material_slot_index"))
        self.assertEqual("source_mat", getattr(edited_submesh, "cdmw_source_texture_set_key"))
        self.assertEqual({"roughness": 0.35, "metalness": 0.8}, getattr(edited_submesh, "preview_native_material_overrides"))

        recalc = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals"))
        flip = service.apply_command(view.session_id, MeshEditCommand("flip_normals"))
        self.assertTrue(recalc.ok)
        self.assertTrue(flip.ok)

    def test_recalculate_normals_noops_when_normals_are_already_current(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="normal-noop", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        clean = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals", selection=selection))
        service.working_mesh(view.session_id).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        stale = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals", selection=selection))

        self.assertTrue(clean.ok)
        self.assertEqual((), clean.affected_submesh_indices)
        self.assertTrue(stale.ok)
        self.assertEqual((0,), stale.affected_submesh_indices)
        self.assertEqual(1, service.session_view(view.session_id).revision)

    def test_recalculate_normals_uses_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        mesh = _quad_mesh()
        mesh.submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-normal-recalc", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("resident native normal session not used"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(0, 4)),), result.changed_vertices_by_submesh)
        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, submesh.normals)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_weighted_normals_use_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-weighted-normal", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        submesh.normals = [(1.0, 0.0, 0.0)] * 4
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("resident native weighted-normal session not used"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("weighted_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        refreshed = service.working_mesh(view.session_id).submeshes[0]
        self.assertNotEqual([(1.0, 0.0, 0.0)] * 4, refreshed.normals)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_flip_normals_use_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-flip-normal", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("resident native flip-normal session not used"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)
        refreshed = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual([(0, 2, 1), (1, 3, 2)], refreshed.faces)
        self.assertEqual(4, len(refreshed.normals))
        self.assertEqual((0.0, 0.0, -1.0), refreshed.normals[0])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_flip_normals_source_selection_uses_native_whole_submesh_before_python_face_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id="native-flip-normal-source", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with (
            patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("resident native flip-normal session not used"),
            ),
            patch("cdmw.modding.mesh_edit_ops._selected_faces", side_effect=AssertionError("python normal-flip source face expansion reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_generate_tangents_fills_tangent_channel_and_clears_export_warning(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="tangent-generate", mode="edit")
        before_report = service.validate_export(view.session_id, available_textures=("a.dds",))

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        submesh = service.working_mesh(view.session_id).submeshes[0]
        after_report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, len(getattr(submesh, "tangents", ())))
        self.assertAlmostEqual(1.0, submesh.tangents[0][0], places=6)
        self.assertAlmostEqual(0.0, submesh.tangents[0][1], places=6)
        self.assertAlmostEqual(0.0, submesh.tangents[0][2], places=6)
        self.assertIn("missing_tangents", {issue.code for issue in before_report.warnings})
        self.assertNotIn("missing_tangents", {issue.code for issue in after_report.warnings})

    def test_generate_tangents_uses_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-tangent-generate", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("resident native tangent session not used"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual(0, len(submesh.tangents))
        refreshed = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual(4, len(refreshed.tangents))
        self.assertAlmostEqual(1.0, refreshed.tangents[0][0], places=6)
        self.assertAlmostEqual(0.0, refreshed.tangents[0][1], places=6)
        self.assertAlmostEqual(0.0, refreshed.tangents[0][2], places=6)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_large_generate_tangents_blocks_python_fallback_when_native_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id="large-tangent-generate", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("resident native tangent session not used"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
                )

            self.assertTrue(result.ok)
            self.assertEqual((0,), result.affected_submesh_indices)
            self.assertEqual(10_001, len(service.working_mesh(view.session_id).submeshes[0].tangents))
            self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())
        finally:
            mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_native_mesh_core_generate_tangents_applies_report(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(1,), (2, 3), (4,), (5,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (0.25, 0.75), (1.0,), (1.0,)]
        mesh.submeshes[0].source_vertex_map = [10, 11, 12, 13]
        mesh.submeshes[0].source_vertex_offsets = [100, 110, 120, 130]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("generate-tangents-json", command)
            self.assertEqual("generate_tangents", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("uvs_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            self.assertIn("tangents_output_path", submesh_payload)
            self.assertIn("vertices_output_path", submesh_payload)
            self.assertIn("faces_output_path", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("normals_output_path", submesh_payload)
            self.assertIn("tangent_signs_output_path", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertIn("bone_counts_binary", submesh_payload)
            self.assertIn("bone_counts_output_path", submesh_payload)
            self.assertEqual(10, submesh_payload["source_vertex_map_start"])
            self.assertEqual(4, submesh_payload["source_vertex_map_count"])
            self.assertNotIn("source_vertex_map_binary", submesh_payload)
            self.assertIn("source_vertex_map_output_path", submesh_payload)
            self.assertEqual(100, submesh_payload["source_vertex_offsets_start"])
            self.assertEqual(4, submesh_payload["source_vertex_offsets_count"])
            self.assertEqual(10, submesh_payload["source_vertex_offsets_stride"])
            self.assertNotIn("source_vertex_offsets_binary", submesh_payload)
            self.assertIn("source_vertex_offsets_output_path", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("normals", submesh_payload)
            self.assertEqual(4, submesh_payload["vertices_binary"]["count"])
            self.assertEqual(4, submesh_payload["uvs_binary"]["count"])
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertTrue(Path(submesh_payload["uvs_binary"]["path"]).is_file())
            self.assertEqual(5.0, timeout_seconds)
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            tangent_signs_output_path = Path(str(submesh_payload["tangent_signs_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertex_data = array("d")
            for vertex in (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
            ):
                vertex_data.extend(vertex)
            vertices_output_path.write_bytes(vertex_data.tobytes())
            faces_output_path.write_bytes(array("i", (0, 1, 2, 3, 4, 2)).tobytes())
            uv_data = array("d")
            for uv in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            normal_data = array("d")
            for _index in range(5):
                normal_data.extend((0.0, 0.0, 1.0))
            normals_output_path.write_bytes(normal_data.tobytes())
            tangent_data = array("d")
            for tangent in (
                (0.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ):
                tangent_data.extend(tangent)
            tangents_output_path.write_bytes(tangent_data.tobytes())
            tangent_signs_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, -1.0, 1.0)).tobytes())
            changed_vertices_output_path.write_bytes(array("i", (0, 1, 2, 3, 4)).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 2, 1, 2, 1)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (1, 2, 3, 4, 2, 3, 5)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 0.25, 0.75, 1.0, 0.25, 0.75, 1.0)).tobytes())
            source_map_output_path.write_bytes(array("i", (10, 11, 12, 11, 13)).tobytes())
            source_offsets_output_path.write_bytes(array("i", (100, 110, 120, 110, 130)).tobytes())
            return {
                "status": "ok",
                "tangent_backend": "mikktspace_reference",
                "remap": "vertex_average_after_face_corner_output",
                "face_corner_remap": "face_corner_tangents_reported_vertex_storage_averaged",
                "submeshes": [
                    {
                        "index": 0,
                        "tangent_backend": "mikktspace_reference",
                        "face_corner_remap": "mikktspace_face_corner_tangents_reported_vertex_storage_averaged",
                        "face_corner_tangent_count": 6,
                        "degenerate_uv_faces": 0,
                        "vertex_storage_safe": False,
                        "topology_split_applied": True,
                        "output_vertex_count": 5,
                        "output_face_count": 2,
                        "split_required_vertices": [1],
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 5,
                            "components": 2,
                            "type": "f64",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangent_signs_binary": {
                            "path": str(tangent_signs_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "f64",
                        },
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 7,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 7,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_map_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_offsets_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._apply_vertex_aligned_topology_result",
                side_effect=AssertionError("native subdivide report should not need Python vertex remap"),
            ),
        ):
            affected = mesh_native_core.apply_native_mesh_generate_tangents(mesh, {0})

        self.assertEqual({0}, affected)
        self.assertEqual(5, len(mesh.submeshes[0].vertices))
        self.assertEqual([(0, 1, 2), (3, 4, 2)], mesh.submeshes[0].faces)
        self.assertEqual(
            [(0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            mesh.submeshes[0].tangents,
        )
        self.assertEqual([1.0, 1.0, 1.0, -1.0, 1.0], mesh.submeshes[0].tangent_signs)
        self.assertEqual([(1,), (2, 3), (4,), (2, 3), (5,)], mesh.submeshes[0].bone_indices)
        self.assertEqual([(1.0,), (0.25, 0.75), (1.0,), (0.25, 0.75), (1.0,)], mesh.submeshes[0].bone_weights)
        self.assertEqual([10, 11, 12, 11, 13], mesh.submeshes[0].source_vertex_map)
        self.assertEqual([100, 110, 120, 110, 130], mesh.submeshes[0].source_vertex_offsets)
        self.assertEqual(
            {
                "backend": "mikktspace_reference",
                "face_corner_remap": "mikktspace_face_corner_tangents_reported_vertex_storage_averaged",
                "vertex_storage_safe": True,
                "source_vertex_storage_safe": False,
                "topology_split_applied": True,
                "split_required_vertices": (1,),
            },
            mesh.submeshes[0].tangent_face_corner_report,
        )

    def test_native_mesh_core_generate_tangents_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("uvs_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("generate-tangents-json", command)
            self.assertEqual("generate_tangents", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("uvs_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("normals_binary", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            tangent_data = array("d")
            for tangent in ((0.0, 1.0, 0.0),) * 4:
                tangent_data.extend(tangent)
            tangents_output_path.write_bytes(tangent_data.tobytes())
            changed_vertices_output_path.write_bytes(array("i", (0, 1, 2, 3)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "generate_tangents",
                "submeshes": [
                    {
                        "index": 0,
                        "tangent_backend": "mikktspace_reference",
                        "vertex_storage_safe": True,
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident tangent path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            affected = mesh_native_core.apply_native_mesh_generate_tangents(mesh, {0})

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0}, affected)
        self.assertEqual([(0.0, 1.0, 0.0)] * 4, mesh.submeshes[0].tangents)

    def test_native_tangents_report_trusts_changed_descriptor_without_python_compare(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].tangents = [(1.0, 0.0, 0.0)] * 4
        tangents_path = Path(tempfile.gettempdir()) / f"cdmw-tangents-{uuid4().hex}.bin"
        changed_path = Path(tempfile.gettempdir()) / f"cdmw-tangent-changed-{uuid4().hex}.bin"
        self.addCleanup(lambda: tangents_path.unlink(missing_ok=True))
        self.addCleanup(lambda: changed_path.unlink(missing_ok=True))
        tangent_values = array("d")
        for tangent in ((0.0, 1.0, 0.0),) * 4:
            tangent_values.extend(tangent)
        tangents_path.write_bytes(tangent_values.tobytes())
        changed_path.write_bytes(array("i", (0, 2)).tobytes())
        real_vec3 = mesh_native_core._vec3

        def guarded_vec3(value: object, *, fallback: float = 0.0) -> object:
            if isinstance(value, tuple):
                raise AssertionError("native tangent report apply must not compare every Python tangent")
            return real_vec3(value, fallback=fallback)

        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "generate_tangents",
            "submeshes": [
                {
                    "index": 0,
                    "tangent_backend": "mikktspace_reference",
                    "vertex_storage_safe": True,
                    "tangents_binary": {"path": str(tangents_path), "count": 4, "components": 3, "type": "f64"},
                    "changed_vertices_binary": {"path": str(changed_path), "count": 2, "components": 1, "type": "i32"},
                }
            ],
        }

        with patch("cdmw.modding.mesh_native_core._vec3", side_effect=guarded_vec3):
            affected = mesh_native_core._apply_generate_tangents_report(mesh, report)

        self.assertEqual({0}, affected)
        self.assertEqual((0.0, 1.0, 0.0), mesh.submeshes[0].tangents[2])

    def test_native_mesh_core_cleanup_applies_report(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _duplicate_vertex_mesh()
        mesh.submeshes[0].tangents = [(1.0, 0.0, 0.0)] * 5
        mesh.submeshes[0].tangent_signs = [1.0] * 5
        mesh.submeshes[0].bone_indices = [(0,), (1,), (2,), (3,), (4,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.submeshes[0].source_vertex_map = [10, 11, 12, 13, 14]
        mesh.submeshes[0].source_vertex_offsets = [100, 110, 120, 130, 140]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("cleanup-json", command)
            self.assertEqual("cleanup", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(5, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("vertices_output_path", submesh_payload)
            self.assertIn("faces_output_path", submesh_payload)
            self.assertIs(submesh_payload["suppress_index_map_report"], True)
            self.assertNotIn("index_map_output_path", submesh_payload)
            self.assertIn("normals_output_path", submesh_payload)
            self.assertIn("uvs_binary", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("tangents_binary", submesh_payload)
            self.assertIn("tangents_output_path", submesh_payload)
            self.assertIn("tangent_signs_binary", submesh_payload)
            self.assertIn("tangent_signs_output_path", submesh_payload)
            self.assertIn("bone_counts_binary", submesh_payload)
            self.assertIn("bone_counts_output_path", submesh_payload)
            self.assertEqual(10, submesh_payload["source_vertex_map_start"])
            self.assertEqual(5, submesh_payload["source_vertex_map_count"])
            self.assertNotIn("source_vertex_map_binary", submesh_payload)
            self.assertIn("source_vertex_map_output_path", submesh_payload)
            self.assertEqual(100, submesh_payload["source_vertex_offsets_start"])
            self.assertEqual(5, submesh_payload["source_vertex_offsets_count"])
            self.assertEqual(10, submesh_payload["source_vertex_offsets_stride"])
            self.assertNotIn("source_vertex_offsets_binary", submesh_payload)
            self.assertIn("source_vertex_offsets_output_path", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertEqual(5, submesh_payload["vertices_binary"]["count"])
            self.assertEqual(3, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertEqual(0.001, payload["cleanup"]["threshold"])  # type: ignore[index]
            self.assertEqual(5.0, timeout_seconds)
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            tangent_signs_output_path = Path(str(submesh_payload["tangent_signs_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertex_data = array("d")
            for vertex in (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
            ):
                vertex_data.extend(vertex)
            vertices_output_path.write_bytes(vertex_data.tobytes())
            faces_output_path.write_bytes(array("i", (0, 1, 2, 1, 3, 2)).tobytes())
            normal_data = array("d")
            tangent_data = array("d")
            for normal, tangent in zip(
                ((0.0, 0.0, 2.0),) * 4,
                ((2.0, 0.0, 0.0),) * 4,
            ):
                normal_data.extend(normal)
                tangent_data.extend(tangent)
            normals_output_path.write_bytes(normal_data.tobytes())
            tangents_output_path.write_bytes(tangent_data.tobytes())
            uv_data = array("d")
            for uv in ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0), (2.0, 2.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            tangent_signs_output_path.write_bytes(array("d", (1.0, -1.0, 1.0, -1.0)).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 1, 1, 1)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (0, 1, 2, 3)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, 1.0)).tobytes())
            source_map_output_path.write_bytes(array("i", (20, 21, 22, 23)).tobytes())
            source_offsets_output_path.write_bytes(array("i", (200, 210, 220, 230)).tobytes())
            return {
                "status": "ok",
                "submeshes": [
                    {
                        "index": 0,
                        "removed_vertices": 1,
                        "removed_faces": 1,
                        "merged_vertices": 1,
                        "degenerate_faces": 1,
                        "duplicate_faces": 0,
                        "index_map_report_suppressed": True,
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 4,
                            "components": 2,
                            "type": "f64",
                        },
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangent_signs_binary": {
                            "path": str(tangent_signs_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "f64",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_map_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_offsets_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._remap_vertex_aligned_list",
                side_effect=AssertionError("native cleanup report must provide final aligned sidecars"),
            ),
        ):
            affected = mesh_native_core.apply_native_mesh_remove_doubles(mesh, {0: {0, 1, 2, 3, 4}}, threshold=0.001)

        self.assertEqual({0}, affected)
        submesh = mesh.submeshes[0]
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)
        self.assertEqual([(0.0, 0.0), (2.0, 0.0), (0.0, 2.0), (2.0, 2.0)], submesh.uvs)
        self.assertEqual([(0.0, 0.0, 2.0)] * 4, submesh.normals)
        self.assertEqual([(2.0, 0.0, 0.0)] * 4, submesh.tangents)
        self.assertEqual([1.0, -1.0, 1.0, -1.0], submesh.tangent_signs)
        self.assertEqual([(0,), (1,), (2,), (3,)], submesh.bone_indices)
        self.assertEqual([(1.0,), (1.0,), (1.0,), (1.0,)], submesh.bone_weights)
        self.assertEqual([20, 21, 22, 23], submesh.source_vertex_map)
        self.assertEqual([200, 210, 220, 230], submesh.source_vertex_offsets)

    def test_native_mesh_core_cleanup_all_vertices_uses_descriptor_not_python_ids(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _duplicate_vertex_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("cleanup-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertTrue(submesh_payload["selected_all_vertices"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "cleanup",
                "submeshes": [],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_remove_doubles(mesh, {0: None}, threshold=0.001)

        self.assertEqual(set(), affected)

    def test_native_mesh_core_cleanup_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _duplicate_vertex_mesh()
        submesh = mesh.submeshes[0]
        submesh.tangents = [(1.0, 0.0, 0.0)] * 5
        submesh.tangent_signs = [1.0] * 5
        submesh.bone_indices = [(0,), (1,), (2,), (3,), (4,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,), (1.0,)]
        submesh.source_vertex_map = [10, 11, 12, 13, 14]
        submesh.source_vertex_offsets = [100, 110, 120, 130, 140]
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("tangents_binary", submesh_payload)
            self.assertIn("bone_counts_binary", submesh_payload)
            self.assertEqual(10, submesh_payload["source_vertex_map_start"])
            self.assertEqual(5, submesh_payload["source_vertex_map_count"])
            self.assertNotIn("source_vertex_map_binary", submesh_payload)
            self.assertEqual(100, submesh_payload["source_vertex_offsets_start"])
            self.assertEqual(5, submesh_payload["source_vertex_offsets_count"])
            self.assertEqual(10, submesh_payload["source_vertex_offsets_stride"])
            self.assertNotIn("source_vertex_offsets_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("cleanup-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(5, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            for key in (
                "vertices_binary",
                "faces_binary",
                "uvs_binary",
                "tangents_binary",
                "tangent_signs_binary",
                "bone_counts_binary",
                "source_vertex_map_binary",
                "source_vertex_offsets_binary",
            ):
                self.assertNotIn(key, submesh_payload)
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            self.assertIs(submesh_payload["suppress_index_map_report"], True)
            self.assertNotIn("index_map_output_path", submesh_payload)
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            tangent_signs_output_path = Path(str(submesh_payload["tangent_signs_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertex_data = array("d")
            for vertex in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)):
                vertex_data.extend(vertex)
            vertices_output_path.write_bytes(vertex_data.tobytes())
            faces_output_path.write_bytes(array("i", (0, 1, 2, 1, 3, 2)).tobytes())
            normal_data = array("d")
            tangent_data = array("d")
            for _index_value in range(4):
                normal_data.extend((0.0, 0.0, 1.0))
                tangent_data.extend((1.0, 0.0, 0.0))
            normals_output_path.write_bytes(normal_data.tobytes())
            tangents_output_path.write_bytes(tangent_data.tobytes())
            uv_data = array("d")
            for uv in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            tangent_signs_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, 1.0)).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 1, 1, 1)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (0, 1, 2, 3)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, 1.0)).tobytes())
            source_map_output_path.write_bytes(array("i", (10, 11, 12, 13)).tobytes())
            source_offsets_output_path.write_bytes(array("i", (100, 110, 120, 130)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "cleanup",
                "submeshes": [
                    {
                        "index": 0,
                        "removed_vertices": 1,
                        "removed_faces": 1,
                        "merged_vertices": 1,
                        "index_map_report_suppressed": True,
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 4,
                            "components": 2,
                            "type": "f64",
                        },
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 4,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangent_signs_binary": {
                            "path": str(tangent_signs_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "f64",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_map_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_offsets_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident cleanup path must not rebuild face sidecars"),
            ),
            patch(
                "cdmw.modding.mesh_native_core._remap_vertex_aligned_list",
                side_effect=AssertionError("resident cleanup report must provide final aligned sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            affected = mesh_native_core.apply_native_mesh_remove_doubles(mesh, {0: {0, 1, 2, 3, 4}}, threshold=0.001)

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0}, affected)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual([10, 11, 12, 13], mesh.submeshes[0].source_vertex_map)

    def test_native_mesh_core_transform_uses_sparse_vertex_payload_without_mirror(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("vertex_positions", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertEqual(4, submesh_payload["vertex_count"])
            self.assertIn("selected_vertices_binary", submesh_payload)
            self.assertIn("vertex_indices_binary", submesh_payload)
            self.assertIn("vertex_positions_binary", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertEqual(2, submesh_payload["vertex_positions_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertex_positions_binary"]["path"]).is_file())
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            changed_vertices_output_path.write_bytes(array("i", (0, 3)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 2,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions": [[0.0, 0.0, 0.5], [1.0, 1.0, 0.5]],
                        "preview_vertex_update_group": {
                            "preview_backend": "cdmw_mesh_core",
                            "source_submesh_index": 0,
                            "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
                            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {0, 3}},
                translate=(0.0, 0.0, 0.5),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
            )

        self.assertEqual({0: {0, 3}}, changed)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.5), mesh.submeshes[0].vertices[3])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])
        self.assertNotIn("source_vertex_indices", mesh.submeshes[0].cdmw_native_preview_vertex_update_group)
        self.assertEqual(
            {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            mesh.submeshes[0].cdmw_native_preview_vertex_update_group["source_vertex_indices_binary"],
        )

    def test_native_mesh_edit_report_trusts_full_native_vertices_without_python_compare(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        real_vec3 = mesh_native_core._vec3

        def guarded_vec3(value: object, *, fallback: float = 0.0) -> object:
            if isinstance(value, tuple):
                raise AssertionError("native report apply must not compare against every Python vertex")
            return real_vec3(value, fallback=fallback)

        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "brush",
            "submeshes": [
                {
                    "index": 0,
                    "changed_vertices": [0],
                    "vertices": [
                        [0.0, 0.0, 0.5],
                        [1.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0],
                        [1.0, 1.0, 0.0],
                    ],
                }
            ],
        }

        with patch("cdmw.modding.mesh_native_core._vec3", side_effect=guarded_vec3):
            applied = mesh_native_core._apply_mesh_edit_report(mesh, report)

        self.assertEqual(({0}, {0: {0}}), applied)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])

    def test_native_sparse_edit_report_ignores_empty_non_topology_uv_sidecar(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory(prefix="cdmw_sparse_report_empty_uvs_") as temp_dir:
            root = Path(temp_dir)
            changed_positions_path = root / "changed_positions.bin"
            uvs_path = root / "uvs.bin"
            changed_positions_path.write_bytes(array("d", (0.0, 0.0, 0.25, 1.0, 0.0, 0.25)).tobytes())
            uvs_path.write_bytes(b"")
            applied = mesh_native_core._apply_mesh_edit_report(
                mesh,
                {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "undo",
                    "submeshes": [
                        {
                            "index": 0,
                            "topology_changed": False,
                            "changed_vertex_start": 0,
                            "changed_vertex_count": 2,
                            "changed_positions_binary": {
                                "path": str(changed_positions_path),
                                "count": 2,
                                "components": 3,
                                "type": "f64",
                                "finite_checked": True,
                            },
                            "uvs_binary": {
                                "path": str(uvs_path),
                                "count": 0,
                                "components": 2,
                                "type": "f64",
                                "finite_checked": True,
                            },
                        }
                    ],
                },
            )

        self.assertEqual(({0}, {0: range(0, 2)}), applied)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.25), mesh.submeshes[0].vertices[1])
        self.assertEqual((0.0, 0.0), mesh.submeshes[0].uvs[0])

    def test_native_mesh_core_transform_reads_before_position_history_sidecar(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            snapshot_id = str(payload["sparse_snapshot_id"])  # type: ignore[index]
            self.assertTrue(snapshot_id.startswith("py-sparse-vertices-transform-"))
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("before_positions_output_path", submesh_payload)
            before_path = Path(str(submesh_payload["before_positions_output_path"]))
            data = array("d", [0.0, 0.0, 0.0])
            with before_path.open("wb") as handle:
                data.tofile(handle)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "native_sparse_snapshot_id": snapshot_id,
                        "changed_vertices": [0],
                        "changed_positions": [[0.0, 0.0, 0.5]],
                        "before_positions_binary": {
                            "path": str(before_path),
                            "count": 1,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {0}},
                translate=(0.0, 0.0, 0.5),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
                history_delta=True,
            )

        delta = mesh.submeshes[0].cdmw_native_mesh_history_vertex_delta
        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])
        self.assertEqual((0,), delta["vertex_indices"])
        self.assertEqual(delta["native_sparse_snapshot_id"], delta["native_sparse_snapshot_id"].strip())
        self.assertTrue(str(delta["native_sparse_snapshot_id"]).startswith("py-sparse-vertices-transform-"))
        self.assertNotIn("before_positions", delta)
        self.assertTrue(Path(str(delta["before_positions_binary"]["path"])).is_file())
        self.assertEqual(((0.0, 0.0, 0.0),), mesh_native_core.native_mesh_history_delta_positions(delta))

    def test_native_mesh_core_history_delta_preserves_range_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            before_path = Path(str(submesh_payload["before_positions_output_path"]))
            before_path.write_bytes(array("d", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": command.removesuffix("-json"),
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertex_start": 0,
                        "changed_vertex_count": 2,
                        "changed_positions": [[0.0, 0.0, 0.5], [1.0, 0.0, 0.5]],
                        "before_positions_binary": {
                            "path": str(before_path),
                            "count": 2,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {0, 1}},
                translate=(0.0, 0.0, 0.5),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
                history_delta=True,
        )

        delta = mesh.submeshes[0].cdmw_native_mesh_history_vertex_delta
        self.assertIsInstance(changed[0], range)  # type: ignore[index]
        self.assertEqual(range(0, 2), changed[0])  # type: ignore[index]
        self.assertEqual(0, delta["vertex_index_start"])
        self.assertEqual(2, delta["vertex_index_count"])
        self.assertNotIn("vertex_indices", delta)
        self.assertEqual(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            mesh_native_core.native_mesh_history_delta_positions(delta),
        )

    def test_native_sparse_vertex_restore_uses_resident_session_payload(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("restore-vertices-json", command)
            snapshot_id = str(payload["sparse_snapshot_id"])  # type: ignore[index]
            self.assertTrue(snapshot_id.startswith("py-sparse-vertices-restore-"))
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertEqual(4, submesh_payload["vertex_count"])
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("vertex_positions", submesh_payload)
            self.assertEqual(0, submesh_payload["vertex_index_start"])
            self.assertEqual(1, submesh_payload["vertex_index_count"])
            self.assertNotIn("vertex_indices_binary", submesh_payload)
            positions = array("d")
            positions.frombytes(Path(submesh_payload["vertex_positions_binary"]["path"]).read_bytes())
            self.assertEqual([0.0, 0.0, 0.0], list(positions))

            changed_vertices_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            changed_positions_path = Path(str(submesh_payload["changed_positions_output_path"]))
            before_path = Path(str(submesh_payload["before_positions_output_path"]))
            changed_vertices_path.write_bytes(array("i", (0,)).tobytes())
            changed_positions_path.write_bytes(array("d", (0.0, 0.0, 0.0)).tobytes())
            before_path.write_bytes(array("d", (0.0, 0.0, 0.5)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "restore_vertices",
                "submeshes": [
                    {
                        "index": 0,
                        "native_sparse_snapshot_id": snapshot_id,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions_binary": {
                            "path": str(changed_positions_path),
                            "count": 1,
                            "components": 3,
                            "type": "f64",
                        },
                        "before_positions_binary": {
                            "path": str(before_path),
                            "count": 1,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_sparse_vertex_restore(
                mesh,
                {0: {0: (0.0, 0.0, 0.0)}},
                history_delta=True,
            )

        delta = mesh.submeshes[0].cdmw_native_mesh_history_vertex_delta
        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])
        self.assertEqual((0,), delta["vertex_indices"])
        self.assertTrue(str(delta["native_sparse_snapshot_id"]).startswith("py-sparse-vertices-restore-"))
        self.assertNotIn("before_positions", delta)
        self.assertTrue(Path(str(delta["before_positions_binary"]["path"])).is_file())
        self.assertEqual(((0.0, 0.0, 0.5),), mesh_native_core.native_mesh_history_delta_positions(delta))

    def test_native_sparse_vertex_restore_accepts_descriptor_groups_without_position_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        first_positions = Path(tempfile.gettempdir()) / f"cdmw-first-{uuid4().hex}.bin"
        second_positions = Path(tempfile.gettempdir()) / f"cdmw-second-{uuid4().hex}.bin"
        first_positions.write_bytes(array("d", (0.0, 0.0, 0.0)).tobytes())
        second_positions.write_bytes(array("d", (1.0, 0.0, 0.0)).tobytes())
        self.addCleanup(lambda: first_positions.unlink(missing_ok=True))
        self.addCleanup(lambda: second_positions.unlink(missing_ok=True))

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("restore-vertices-json", command)
            submesh_payloads = payload["submeshes"]  # type: ignore[index]
            self.assertEqual(2, len(submesh_payloads))
            self.assertEqual("resident-sparse-a", submesh_payloads[0]["native_sparse_snapshot_id"])
            self.assertEqual("resident-sparse-b", submesh_payloads[1]["native_sparse_snapshot_id"])
            self.assertEqual(str(first_positions), submesh_payloads[0]["vertex_positions_binary"]["path"])
            self.assertEqual(str(second_positions), submesh_payloads[1]["vertex_positions_binary"]["path"])
            reports = []
            for offset, submesh_payload in enumerate(submesh_payloads):
                changed_vertices_path = Path(str(submesh_payload["changed_vertices_output_path"]))
                changed_positions_path = Path(str(submesh_payload["changed_positions_output_path"]))
                changed_vertices_path.write_bytes(array("i", (offset,)).tobytes())
                changed_positions_path.write_bytes(array("d", (float(offset), 0.0, 0.0)).tobytes())
                reports.append(
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions_binary": {
                            "path": str(changed_positions_path),
                            "count": 1,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                )
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "restore_vertices",
                "submeshes": reports,
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_sparse_vertex_restore(
                mesh,
                {
                    0: {
                        "groups": [
                            {
                                "vertex_indices": (0,),
                                "native_sparse_snapshot_id": "resident-sparse-a",
                                "before_positions_binary": {
                                    "path": str(first_positions),
                                    "count": 1,
                                    "components": 3,
                                    "type": "f64",
                                },
                            },
                            {
                                "vertex_indices": (1,),
                                "native_sparse_snapshot_id": "resident-sparse-b",
                                "before_positions_binary": {
                                    "path": str(second_positions),
                                    "count": 1,
                                    "components": 3,
                                    "type": "f64",
                                },
                            },
                        ]
                    }
                },
            )

        self.assertEqual({0: {0, 1}}, changed)
        self.assertEqual((0.0, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_native_sparse_vertex_restore_accepts_range_descriptor_group(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        positions_path = Path(tempfile.gettempdir()) / f"cdmw-range-{uuid4().hex}.bin"
        positions_path.write_bytes(array("d", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)).tobytes())
        self.addCleanup(lambda: positions_path.unlink(missing_ok=True))

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("restore-vertices-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["vertex_index_start"])
            self.assertEqual(2, submesh_payload["vertex_index_count"])
            self.assertNotIn("vertex_indices_binary", submesh_payload)
            self.assertEqual(str(positions_path), submesh_payload["vertex_positions_binary"]["path"])
            changed_vertices_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            changed_positions_path = Path(str(submesh_payload["changed_positions_output_path"]))
            changed_vertices_path.write_bytes(array("i", (0, 1)).tobytes())
            changed_positions_path.write_bytes(array("d", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "restore_vertices",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_path),
                            "count": 2,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions_binary": {
                            "path": str(changed_positions_path),
                            "count": 2,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_sparse_vertex_restore(
                mesh,
                {
                    0: {
                        "groups": [
                            {
                                "vertex_index_start": 0,
                                "vertex_index_count": 2,
                                "before_positions_binary": {
                                    "path": str(positions_path),
                                    "count": 2,
                                    "components": 3,
                                    "type": "f64",
                                },
                            }
                        ]
                    }
                },
            )

        self.assertEqual({0: {0, 1}}, changed)
        self.assertEqual((0.0, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_native_sparse_vertex_restore_accepts_handle_when_descriptor_invalid(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)
        invalid_positions = Path(tempfile.gettempdir()) / f"cdmw-invalid-{uuid4().hex}.bin"

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("restore-vertices-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("resident-sparse-only", submesh_payload["native_sparse_snapshot_id"])
            self.assertNotIn("vertex_positions_binary", submesh_payload)
            changed_vertices_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            changed_positions_path = Path(str(submesh_payload["changed_positions_output_path"]))
            changed_vertices_path.write_bytes(array("i", (0,)).tobytes())
            changed_positions_path.write_bytes(array("d", (0.0, 0.0, 0.0)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "restore_vertices",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions_binary": {
                            "path": str(changed_positions_path),
                            "count": 1,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_sparse_vertex_restore(
                mesh,
                {
                    0: {
                        "groups": [
                            {
                                "vertex_indices": (0,),
                                "native_sparse_snapshot_id": "resident-sparse-only",
                                "before_positions_binary": {
                                    "path": str(invalid_positions),
                                    "count": 2,
                                    "components": 3,
                                    "type": "f64",
                                },
                            }
                        ]
                    }
                },
            )

        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.0), mesh.submeshes[0].vertices[0])

    def test_native_sparse_vertex_snapshot_captures_current_positions_without_position_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("snapshot-vertices-json", command)
            snapshot_id = str(payload["sparse_snapshot_id"])  # type: ignore[index]
            self.assertTrue(snapshot_id.startswith("py-sparse-vertices-snapshot-"))
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(0, submesh_payload["vertex_index_start"])
            self.assertEqual(2, submesh_payload["vertex_index_count"])
            self.assertNotIn("vertex_indices_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            changed_vertices_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            before_positions_path = Path(str(submesh_payload["before_positions_output_path"]))
            changed_vertices_path.write_bytes(array("i", (0, 1)).tobytes())
            before_positions_path.write_bytes(array("d", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "snapshot_vertices",
                "submeshes": [
                    {
                        "index": 0,
                        "native_sparse_snapshot_id": snapshot_id,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_path),
                            "count": 2,
                            "components": 1,
                            "type": "i32",
                        },
                        "before_positions_binary": {
                            "path": str(before_positions_path),
                            "count": 2,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            snapshot = mesh_native_core.snapshot_native_mesh_sparse_vertex_positions(
                mesh,
                {
                    0: {
                        "groups": [
                            {
                                "vertex_indices": (0, 1),
                                "before_positions_binary": {
                                    "path": "previous.bin",
                                    "count": 2,
                                    "components": 3,
                                    "type": "f64",
                                },
                            }
                        ]
                    }
                },
            )

        self.assertIsNotNone(snapshot)
        group = snapshot[0]["groups"][0]  # type: ignore[index]
        self.assertEqual((0, 1), group["vertex_indices"])
        self.assertTrue(str(group["native_sparse_snapshot_id"]).startswith("py-sparse-vertices-snapshot-"))
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), mesh_native_core.native_mesh_history_delta_positions(group))

    def test_native_submesh_snapshot_round_trips_without_geometry_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        service_store_payloads: list[object] = []
        snapshot_operations: list[str] = []

        def write_vec3(path: object, values: tuple[tuple[float, float, float], ...]) -> None:
            Path(str(path)).write_bytes(array("d", [component for value in values for component in value]).tobytes())

        def write_vec2(path: object, values: tuple[tuple[float, float], ...]) -> None:
            Path(str(path)).write_bytes(array("d", [component for value in values for component in value]).tobytes())

        def write_i32(path: object, values: tuple[int, ...]) -> None:
            Path(str(path)).write_bytes(array("i", values).tobytes())

        def native_service_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            if command == "mesh-session-json":
                service_store_payloads.append(payload)
                return {"status": "ok", "backend": "cdmw_mesh_core_0.1", "operation": "mesh_session"}
            self.assertEqual("snapshot-submeshes-json", command)
            operation = str(payload["operation"])  # type: ignore[index]
            snapshot_operations.append(operation)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            snapshot_id = str(payload["snapshot_id"])  # type: ignore[index]
            if operation == "restore_snapshot":
                self.assertEqual("session-0", submesh_payload["session_id"])
                self.assertNotIn("vertices_output_path", submesh_payload)
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "restore_snapshot",
                    "snapshot_id": snapshot_id,
                    "restored_submesh_count": 1,
                    "submeshes": [{"index": 0, "session_id": "session-0", "vertex_count": 4, "face_count": 2}],
                }
            self.assertIn("session_id", submesh_payload)
            self.assertIn("vertices_output_path", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            vertices = (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
            )
            faces = ((0, 1, 2), (1, 3, 2))
            normals = ((0.0, 0.0, 1.0),) * 4
            uvs = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
            write_vec3(submesh_payload["vertices_output_path"], vertices)
            write_i32(submesh_payload["faces_output_path"], tuple(index for face in faces for index in face))
            write_vec3(submesh_payload["normals_output_path"], normals)
            write_vec2(submesh_payload["uvs_output_path"], uvs)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": operation,
                "snapshot_id": snapshot_id,
                "snapshot_handle": {
                    "id": snapshot_id,
                    "submesh_count": 1,
                    "vertex_count": len(vertices),
                    "face_count": len(faces),
                },
                "submeshes": [
                    {
                        "index": 0,
                        "session_id": "session-0",
                        "vertex_count": len(vertices),
                        "face_count": len(faces),
                        "vertices_binary": {
                            "path": str(submesh_payload["vertices_output_path"]),
                            "count": len(vertices),
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(submesh_payload["faces_output_path"]),
                            "count": len(faces),
                            "components": 3,
                            "type": "i32",
                        },
                        "source_face_start": 0,
                        "source_face_count": len(faces),
                        "source_vertex_map_start": 10,
                        "source_vertex_map_count": len(vertices),
                        "source_vertex_offsets_start": 100,
                        "source_vertex_offsets_count": len(vertices),
                        "source_vertex_offsets_stride": 10,
                        "normals_binary": {
                            "path": str(submesh_payload["normals_output_path"]),
                            "count": len(normals),
                            "components": 3,
                            "type": "f64",
                        },
                        "uvs_binary": {
                            "path": str(submesh_payload["uvs_output_path"]),
                            "count": len(uvs),
                            "components": 2,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=native_service_job),
        ):
            snapshot = mesh_native_core.snapshot_native_mesh_submeshes(mesh)
            self.assertIsNotNone(snapshot)
            self.assertIsNotNone(snapshot["handle"])  # type: ignore[index]
            snapshot_item = snapshot["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, snapshot_item["source_face_start"])
            self.assertEqual(2, snapshot_item["source_face_count"])
            self.assertNotIn("source_face_indices_binary", snapshot_item)
            self.assertEqual(10, snapshot_item["source_vertex_map_start"])
            self.assertEqual(4, snapshot_item["source_vertex_map_count"])
            self.assertNotIn("source_vertex_map_binary", snapshot_item)
            self.assertEqual(100, snapshot_item["source_vertex_offsets_start"])
            self.assertEqual(4, snapshot_item["source_vertex_offsets_count"])
            self.assertEqual(10, snapshot_item["source_vertex_offsets_stride"])
            self.assertNotIn("source_vertex_offsets_binary", snapshot_item)
            mesh.submeshes[0].vertices = [(9.0, 9.0, 9.0)]
            mesh.submeshes[0].faces = []
            restored = mesh_native_core.restore_native_mesh_submesh_snapshot(mesh, snapshot)  # type: ignore[arg-type]

        self.assertTrue(restored)
        self.assertEqual(["snapshot_submeshes", "restore_snapshot"], snapshot_operations)
        self.assertEqual("quad", mesh.submeshes[0].name)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual((0.0, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual([(0, 1, 2), (1, 3, 2)], mesh.submeshes[0].faces)
        self.assertEqual([10, 11, 12, 13], mesh.submeshes[0].source_vertex_map)
        self.assertEqual([100, 110, 120, 130], mesh.submeshes[0].source_vertex_offsets)
        self.assertEqual([], service_store_payloads)

    def test_native_submesh_restore_from_mesh_targets_resident_session(self) -> None:
        from cdmw.modding import mesh_native_core

        source = _quad_mesh(two_parts=True)
        target = _quad_mesh(two_parts=True)
        source.submeshes[0].material = "mat_reset"
        source.submeshes[0].vertices[0] = (2.0, 0.0, 0.0)
        target.submeshes[0].material = "mat_dirty"
        target.submeshes[0].vertices = [(9.0, 9.0, 9.0)]
        target.submeshes[0].faces = []
        untouched_vertices = list(target.submeshes[1].vertices)
        operations: list[str] = []
        restored_session_ids: list[str] = []
        stored_payloads: list[object] = []

        def write_vec3(path: object, values: tuple[tuple[float, float, float], ...]) -> None:
            Path(str(path)).write_bytes(array("d", [component for value in values for component in value]).tobytes())

        def write_vec2(path: object, values: tuple[tuple[float, float], ...]) -> None:
            Path(str(path)).write_bytes(array("d", [component for value in values for component in value]).tobytes())

        def write_i32(path: object, values: tuple[int, ...]) -> None:
            Path(str(path)).write_bytes(array("i", values).tobytes())

        def native_service_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            if command == "mesh-session-json":
                stored_payloads.append(payload)
                return {"status": "ok", "backend": "cdmw_mesh_core_0.1", "operation": "mesh_session"}
            self.assertEqual("snapshot-submeshes-json", command)
            self.assertIsInstance(payload, Mapping)
            operation = str(payload["operation"])
            operations.append(operation)
            snapshot_id = str(payload["snapshot_id"])
            if operation == "clear_snapshot":
                return {"status": "ok", "backend": "cdmw_mesh_core_0.1", "operation": "clear_snapshot", "snapshot_id": snapshot_id}
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            if operation == "restore_snapshot":
                restored_session_ids.append(str(submesh_payload["session_id"]))
                self.assertNotEqual("source-session-0", submesh_payload["session_id"])
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "restore_snapshot",
                    "snapshot_id": snapshot_id,
                    "restored_submesh_count": 1,
                    "submeshes": [
                        {
                            "index": 0,
                            "session_id": submesh_payload["session_id"],
                            "vertex_count": 4,
                            "face_count": 2,
                        }
                    ],
                }
            vertices = tuple(source.submeshes[0].vertices)
            faces = tuple(source.submeshes[0].faces)
            normals = tuple(source.submeshes[0].normals)
            uvs = tuple(source.submeshes[0].uvs)
            write_vec3(submesh_payload["vertices_output_path"], vertices)
            write_i32(submesh_payload["faces_output_path"], tuple(index for face in faces for index in face))
            write_vec3(submesh_payload["normals_output_path"], normals)
            write_vec2(submesh_payload["uvs_output_path"], uvs)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": operation,
                "snapshot_id": snapshot_id,
                "snapshot_handle": {
                    "id": snapshot_id,
                    "submesh_count": 1,
                    "vertex_count": len(vertices),
                    "face_count": len(faces),
                },
                "submeshes": [
                    {
                        "index": 0,
                        "session_id": submesh_payload["session_id"],
                        "vertex_count": len(vertices),
                        "face_count": len(faces),
                        "vertices_binary": {
                            "path": str(submesh_payload["vertices_output_path"]),
                            "count": len(vertices),
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(submesh_payload["faces_output_path"]),
                            "count": len(faces),
                            "components": 3,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(submesh_payload["normals_output_path"]),
                            "count": len(normals),
                            "components": 3,
                            "type": "f64",
                        },
                        "uvs_binary": {
                            "path": str(submesh_payload["uvs_output_path"]),
                            "count": len(uvs),
                            "components": 2,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="source-session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=native_service_job),
        ):
            restored = mesh_native_core.restore_native_mesh_submeshes_from_mesh(target, source, (0,))

        self.assertTrue(restored)
        self.assertEqual(["snapshot_submeshes", "restore_snapshot", "export_snapshot", "clear_snapshot"], operations)
        self.assertEqual(1, len(restored_session_ids))
        self.assertEqual([], stored_payloads)
        self.assertEqual("mat_reset", target.submeshes[0].material)
        self.assertEqual((2.0, 0.0, 0.0), target.submeshes[0].vertices[0])
        self.assertEqual(list(source.submeshes[0].faces), target.submeshes[0].faces)
        self.assertEqual(untouched_vertices, target.submeshes[1].vertices)

    def test_native_mesh_core_submesh_snapshot_reports_source_map_and_offsets_as_ranges(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [10, 11, 12, 13]
        mesh.submeshes[0].source_vertex_offsets = [100, 110, 120, 130]
        snapshot: Mapping[str, object] | None = None
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            snapshot = mesh_native_core.snapshot_native_mesh_submeshes(mesh, timeout_seconds=5.0)  # type: ignore[assignment]
            self.assertIsNotNone(snapshot)
            item = snapshot["submeshes"][0]  # type: ignore[index]
            self.assertEqual(10, item["source_vertex_map_start"])  # type: ignore[index]
            self.assertEqual(4, item["source_vertex_map_count"])  # type: ignore[index]
            self.assertNotIn("source_vertex_map_binary", item)
            self.assertEqual(100, item["source_vertex_offsets_start"])  # type: ignore[index]
            self.assertEqual(4, item["source_vertex_offsets_count"])  # type: ignore[index]
            self.assertEqual(10, item["source_vertex_offsets_stride"])  # type: ignore[index]
            self.assertNotIn("source_vertex_offsets_binary", item)
        finally:
            if snapshot is not None:
                mesh_native_core.dispose_native_mesh_submesh_snapshot(snapshot)
            mesh_native_core._cleanup_native_preview_delta_paths()
            mesh_native_core._clear_native_mesh_core_session_cache()

    def test_native_submesh_snapshot_forwards_source_face_range_to_session_restore(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vertices = (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
            )
            faces = ((0, 1, 2), (1, 3, 2))
            vertices_path = root / "vertices.bin"
            faces_path = root / "faces.bin"
            vertices_path.write_bytes(array("d", [component for vertex in vertices for component in vertex]).tobytes())
            faces_path.write_bytes(array("i", [index for face in faces for index in face]).tobytes())
            snapshot = {
                "kind": "native_submesh_snapshot",
                "mesh": {"path": "quad.pac", "format": "pac", "bbox_min": (0.0, 0.0, 0.0), "bbox_max": (1.0, 1.0, 0.0)},
                "submeshes": [
                    {
                        "index": 0,
                        "session_id": "session-0",
                        "metadata": {"name": "quad", "material": "mat_a", "texture": "a.dds"},
                        "vertex_count": len(vertices),
                        "face_count": len(faces),
                        "vertices_binary": {"path": str(vertices_path), "count": len(vertices), "components": 3, "type": "f64"},
                        "faces_binary": {"path": str(faces_path), "count": len(faces), "components": 3, "type": "i32"},
                        "source_face_start": 0,
                        "source_face_count": len(faces),
                        "source_vertex_map_start": 10,
                        "source_vertex_map_count": len(vertices),
                        "source_vertex_offsets_start": 100,
                        "source_vertex_offsets_count": len(vertices),
                        "source_vertex_offsets_stride": 10,
                    }
                ],
            }
            service_store_payloads: list[Mapping[str, object]] = []

            def native_service_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
                self.assertEqual("mesh-session-json", command)
                self.assertIsInstance(payload, Mapping)
                service_store_payloads.append(payload)  # type: ignore[arg-type]
                return {"status": "ok", "backend": "cdmw_mesh_core_0.1", "operation": "mesh_session"}

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=native_service_job),
            ):
                restored = mesh_native_core.restore_native_mesh_submesh_snapshot(mesh, snapshot)

        self.assertTrue(restored)
        self.assertEqual(1, len(service_store_payloads))
        stored_submesh = service_store_payloads[0]["submeshes"][0]  # type: ignore[index]
        self.assertEqual(0, stored_submesh["source_face_start"])  # type: ignore[index]
        self.assertEqual(2, stored_submesh["source_face_count"])  # type: ignore[index]
        self.assertNotIn("source_face_indices_binary", stored_submesh)
        self.assertEqual(10, stored_submesh["source_vertex_map_start"])  # type: ignore[index]
        self.assertEqual(4, stored_submesh["source_vertex_map_count"])  # type: ignore[index]
        self.assertNotIn("source_vertex_map_binary", stored_submesh)
        self.assertEqual(100, stored_submesh["source_vertex_offsets_start"])  # type: ignore[index]
        self.assertEqual(4, stored_submesh["source_vertex_offsets_count"])  # type: ignore[index]
        self.assertEqual(10, stored_submesh["source_vertex_offsets_stride"])  # type: ignore[index]
        self.assertNotIn("source_vertex_offsets_binary", stored_submesh)

    def test_native_submesh_snapshot_restore_strips_transient_preview_attrs(self) -> None:
        from cdmw.modding import mesh_native_core

        with tempfile.TemporaryDirectory(prefix="cdmw_snapshot_transient_") as temp_dir:
            root = Path(temp_dir)
            vertices_path = root / "vertices.bin"
            faces_path = root / "faces.bin"
            vertices_path.write_bytes(array("d", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)).tobytes())
            faces_path.write_bytes(array("i", (0, 1, 2)).tobytes())
            mesh = _quad_mesh()
            snapshot = {
                "kind": "native_submesh_snapshot",
                "mesh": {"path": "restored.pac", "format": "pac"},
                "submeshes": [
                    {
                        "index": 0,
                        "vertex_count": 3,
                        "face_count": 1,
                        "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
                        "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
                        "metadata": {
                            "name": "restored",
                            "material": "mat",
                            "texture": "a.dds",
                            "extra_attrs": {
                                "cdmw_mesh_edit_material_source_submesh_index": 4,
                                "cdmw_native_preview_triangle_group": {"preview_backend": "cdmw_mesh_core"},
                                "cdmw_native_preview_vertex_update_group": {"preview_backend": "cdmw_mesh_core"},
                                mesh_native_core.NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR: {"changed_vertices": [0]},
                            },
                        },
                    }
                ],
            }

            restored = mesh_native_core.restore_native_mesh_submesh_snapshot(mesh, snapshot)

        self.assertTrue(restored)
        self.assertEqual(4, mesh.submeshes[0].cdmw_mesh_edit_material_source_submesh_index)
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group"))
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_vertex_update_group"))
        self.assertFalse(hasattr(mesh.submeshes[0], mesh_native_core.NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR))

    def test_native_submesh_snapshot_dispose_clears_resident_handle(self) -> None:
        from cdmw.modding import mesh_native_core

        payloads: list[tuple[str, Mapping[str, object]]] = []

        def native_service_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertIsInstance(payload, Mapping)
            payloads.append((command, payload))  # type: ignore[arg-type]
            return {"status": "ok", "operation": "clear_snapshot", "snapshot_id": payload["snapshot_id"]}  # type: ignore[index]

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=native_service_job),
        ):
            disposed = mesh_native_core.dispose_native_mesh_submesh_snapshot(
                {
                    "kind": "native_submesh_snapshot",
                    "handle": {"id": "resident-snapshot-1"},
                    "submeshes": [],
                }
            )

        self.assertTrue(disposed)
        self.assertEqual(1, len(payloads))
        command, payload = payloads[0]
        self.assertEqual("snapshot-submeshes-json", command)
        self.assertEqual("clear_snapshot", payload["operation"])
        self.assertEqual("resident-snapshot-1", payload["snapshot_id"])

    def test_native_sparse_vertex_snapshot_dispose_clears_resident_handle(self) -> None:
        from cdmw.modding import mesh_native_core

        payloads: list[tuple[str, Mapping[str, object]]] = []

        def native_service_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertIsInstance(payload, Mapping)
            payloads.append((command, payload))  # type: ignore[arg-type]
            return {
                "status": "ok",
                "operation": "clear_sparse_snapshot",
                "native_sparse_snapshot_id": payload["sparse_snapshot_id"],  # type: ignore[index]
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=native_service_job),
        ):
            disposed = mesh_native_core.dispose_native_mesh_sparse_vertex_snapshot("resident-sparse-1")

        self.assertTrue(disposed)
        self.assertEqual(1, len(payloads))
        command, payload = payloads[0]
        self.assertEqual("snapshot-vertices-json", command)
        self.assertEqual("clear_sparse_snapshot", payload["operation"])
        self.assertEqual("resident-sparse-1", payload["sparse_snapshot_id"])

    def test_topology_history_uses_resident_native_history_before_clone_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-topology-history", mode="edit")
        original_vertices = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
        original_faces = tuple(tuple(face) for face in service.working_mesh(view.session_id).submeshes[0].faces)

        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("python/native snapshot fallback")),
            patch("cdmw.services.mesh_service.restore_native_mesh_submesh_snapshot", side_effect=AssertionError("python/native restore fallback")),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone fallback")),
        ):
            deleted = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: {0}}),
                ),
            )
            undo = service.undo(view.session_id)

        self.assertTrue(deleted.topology_changed)
        self.assertTrue(undo.ok)
        self.assertTrue(undo.topology_changed)
        self.assertEqual((0,), undo.affected_submesh_indices)
        self.assertEqual(list(original_vertices), service.working_mesh(view.session_id).submeshes[0].vertices)
        self.assertEqual(list(original_faces), service.working_mesh(view.session_id).submeshes[0].faces)

    def test_resident_native_history_does_not_create_python_snapshot_handles(self) -> None:
        service = MeshService(max_history=1)
        view = service.open_edit_session(_quad_mesh(), session_id="native-topology-cleanup", mode="edit")

        with (
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", side_effect=AssertionError("python/native snapshot fallback")),
            patch("cdmw.services.mesh_service.restore_native_mesh_submesh_snapshot", side_effect=AssertionError("python/native restore fallback")),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot", side_effect=AssertionError("python/native snapshot dispose")),
        ):
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: {0}}),
                ),
            )
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "subdivide",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: {0}}),
                ),
            )
            service.undo(view.session_id)
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete",
                    mode="edit",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: {0}}),
                ),
            )
            service.close_edit_session(view.session_id)

        self.assertNotIn(view.session_id, service._sessions)

    def test_native_mesh_core_transform_can_compute_implicit_pivot_in_native(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            transform = payload["transform"]  # type: ignore[index]
            self.assertTrue(transform["pivot_from_selection"])
            self.assertEqual([0.0, 0.0, 0.0], transform["pivot"])
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertEqual(1, submesh_payload["vertex_index_start"])
            self.assertEqual(2, submesh_payload["vertex_index_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertex_indices_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices": [1],
                        "changed_positions": [[1.0, 0.0, 0.5]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {1, 2}},
                translate=(0.0, 0.0, 0.5),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=None,
            )

        self.assertEqual({0: {1}}, changed)
        self.assertEqual((1.0, 0.0, 0.5), mesh.submeshes[0].vertices[1])

    def test_native_mesh_core_transform_uses_binary_vertex_payload_with_mirror(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertNotIn("vertices", submesh_payload)
            self.assertIn("vertices_binary", submesh_payload)
            self.assertEqual(4, submesh_payload["vertices_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertEqual([[0, 1], [1, 0]], submesh_payload["mirror_pairs"])
            self.assertTrue(payload["transform"]["mirror_x"])  # type: ignore[index]
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices": [0, 1],
                        "changed_positions": [[0.25, 0.0, 0.0], [0.75, 0.0, 0.0]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {0}},
                translate=(0.25, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
                mirror_x=True,
                mirror_pairs_by_submesh={0: {0: 1, 1: 0}},
            )

        self.assertEqual({0: {0, 1}}, changed)
        self.assertEqual((0.25, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((0.75, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_native_mesh_core_transform_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertTrue(submesh_payload["sparse_output"])
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("vertex_positions_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices": [0],
                        "changed_positions": [[0.0, 0.0, 0.25]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            changed = mesh_native_core.apply_native_mesh_transform(
                mesh,
                {0: {0}},
                translate=(0.0, 0.0, 0.25),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
                mirror_x=True,
            )

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])

    def test_native_mesh_core_transform_binary_selection_passes_d3d11_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            selected_path = Path(temp_dir) / "selected.bin"
            selected_path.write_bytes(array("i", (0, 3)).tobytes())

            def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
                self.assertEqual("transform-json", command)
                submesh_payload = payload["submeshes"][0]  # type: ignore[index]
                self.assertEqual("session-0", submesh_payload["session_id"])
                self.assertTrue(submesh_payload["sparse_output"])
                self.assertEqual(str(selected_path), submesh_payload["selected_vertices_binary"]["path"])
                self.assertNotIn("selected_vertices", submesh_payload)
                self.assertNotIn("vertices_binary", submesh_payload)
                self.assertNotIn("vertex_positions_binary", submesh_payload)
                self.assertEqual([0.0, 0.0, 0.25], payload["transform"]["translate"])  # type: ignore[index]
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "transform",
                    "submeshes": [
                        {
                            "index": 0,
                            "changed_vertices": [0, 3],
                            "changed_positions": [[0.0, 0.0, 0.25], [1.0, 1.0, 0.25]],
                        }
                    ],
                }

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
                patch(
                    "cdmw.modding.mesh_native_core._face_json",
                    side_effect=AssertionError("binary D3D11 transform path must not rebuild face sidecars"),
                ),
            ):
                changed = mesh_native_core.apply_native_mesh_transform_binary_selection(
                    mesh,
                    selected_vertices_binary_by_submesh={
                        0: {"path": str(selected_path), "count": 2, "components": 1, "type": "i32", "delete_after": True},
                    },
                    translate=(0.0, 0.0, 0.25),
                    scale=(1.0, 1.0, 1.0),
                    rotate=(0.0, 0.0, 0.0),
                    pivot=(0.0, 0.0, 0.0),
                )

        self.assertEqual({0: {0, 3}}, changed)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.25), mesh.submeshes[0].vertices[3])

    def test_native_mesh_core_transform_binary_selection_preserves_d3d11_range(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                        "changed_positions": [[1.0, 0.0, 0.25], [1.0, 1.0, 0.25]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._write_int_binary_payload",
                side_effect=AssertionError("range D3D11 transform path must not write selection sidecars"),
            ),
        ):
            changed = mesh_native_core.apply_native_mesh_transform_binary_selection(
                mesh,
                selected_vertices_binary_by_submesh={0: {"start": 1, "count": 2, "components": 1, "type": "i32_range"}},
                translate=(0.0, 0.0, 0.25),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=(0.0, 0.0, 0.0),
            )

        self.assertEqual({0: range(1, 3)}, changed)
        self.assertEqual((1.0, 0.0, 0.25), mesh.submeshes[0].vertices[1])
        self.assertEqual((1.0, 1.0, 0.25), mesh.submeshes[0].vertices[2])

    def test_transform_binary_selection_failure_does_not_fall_back_to_python_vertices(self) -> None:
        import cdmw.modding.mesh_edit_ops as mesh_edit_ops

        mesh = _quad_mesh()
        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_binary_selection", return_value=None), patch(
            "cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection",
            side_effect=AssertionError("binary descriptor failure must not expand selection domains"),
        ), patch(
            "cdmw.modding.mesh_edit_ops.apply_native_mesh_transform",
            side_effect=AssertionError("binary descriptor failure must not call legacy native transform"),
        ), patch(
            "cdmw.modding.mesh_edit_ops.apply_vertex_delta",
            side_effect=AssertionError("binary descriptor failure must not enter Python transform loop"),
        ):
            affected, changed = mesh_edit_ops.apply_mesh_edit_geometry_action(
                mesh,
                MeshEditCommand(
                    "transform",
                    params={
                        "native_selected_vertices_binary_by_submesh": {
                            0: {"path": "missing.bin", "count": 1, "components": 1, "type": "i32"},
                        },
                        "delta": (0.0, 0.0, 0.25),
                    },
                ),
                MeshEditSelection(),
            )

        self.assertEqual(set(), affected)
        self.assertEqual({}, changed)

    def test_native_mesh_core_transform_selection_uses_resident_selection_domains(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        cancel_event = threading.Event()

        def ensure_session(
            _binary: Path,
            _mesh: ParsedMesh,
            submesh_index: int,
            *,
            stop_event: threading.Event | None = None,
            timeout_seconds: float,
        ) -> str:
            self.assertEqual(0, submesh_index)
            self.assertIs(stop_event, stop_event_token)
            return "session-0"

        stop_event_token = cancel_event

        def native_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            timeout_seconds: float,
            stop_event: threading.Event | None = None,
        ) -> dict[str, object]:
            self.assertEqual("transform-json", command)
            self.assertIs(stop_event, stop_event_token)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertTrue(submesh_payload["sparse_output"])
            self.assertEqual(0, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("vertex_positions_binary", submesh_payload)
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertTrue(payload["transform"]["pivot_from_selection"])  # type: ignore[index]
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices": [0, 1, 2],
                        "changed_positions": [[0.0, 0.0, 0.25], [1.0, 0.0, 0.25], [0.0, 1.0, 0.25]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", side_effect=ensure_session),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_transform_selection(
                mesh,
                vertices_by_submesh={},
                edges_by_submesh={},
                faces_by_submesh={0: {0}},
                source_indices=(),
                translate=(0.0, 0.0, 0.25),
                scale=(1.0, 1.0, 1.0),
                rotate=(0.0, 0.0, 0.0),
                pivot=None,
                stop_event=cancel_event,
            )

        self.assertEqual({0: {0, 1, 2}}, changed)
        self.assertEqual((0.0, 1.0, 0.25), mesh.submeshes[0].vertices[2])

    def test_native_mesh_core_brush_edit_json_applies_vertices(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("brush", payload["operation"])  # type: ignore[index]
            self.assertEqual("grab", payload["edit"]["tool"])  # type: ignore[index]
            self.assertTrue(payload["edit"]["sparse_output"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("normals", submesh_payload)
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertEqual(4, submesh_payload["vertices_binary"]["count"])
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            changed_vertices_output_path.write_bytes(array("i", (0,)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "brush",
                "topology_changed": False,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "brush",
                        "topology_changed": False,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "changed_positions": [[0.0, 0.0, 0.5]],
                        "faces": [],
                        "copy_vertex_indices": [],
                        "vertex_blends": [],
                        "index_map": [],
                        "preview_vertex_update_group": {
                            "preview_backend": "cdmw_mesh_core",
                            "source_submesh_index": 0,
                            "source_vertex_indices": [0],
                            "positions": [0.0, 0.0, 0.5],
                            "normals": [],
                            "uvs": [],
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_brush(
                mesh,
                {0: {0}},
                {"tool": "grab", "drag_delta": (0.0, 0.0, 0.5), "recompute_normals": False},
            )

        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])
        self.assertEqual(2, mesh.submeshes[0].face_count)
        self.assertEqual([0], mesh.submeshes[0].cdmw_native_preview_vertex_update_group["source_vertex_indices"])

    def test_native_mesh_core_brush_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertTrue(submesh_payload["sparse_output"])
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("normals_binary", submesh_payload)
            self.assertNotIn("uvs_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "brush",
                "topology_changed": False,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "brush",
                        "topology_changed": False,
                        "changed_vertices": [0],
                        "changed_positions": [[0.0, 0.0, 0.5]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident brush path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            changed = mesh_native_core.apply_native_mesh_brush(
                mesh,
                {0: {0}},
                {"tool": "grab", "drag_delta": (0.0, 0.0, 0.5), "recompute_normals": False},
            )

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0: {0}}, changed)
        self.assertEqual((0.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])

    def test_native_mesh_core_brush_selection_uses_resident_selection_domains(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        cancel_event = threading.Event()

        def ensure_session(
            _binary: Path,
            _mesh: ParsedMesh,
            submesh_index: int,
            *,
            stop_event: threading.Event | None = None,
            timeout_seconds: float,
        ) -> str:
            self.assertEqual(0, submesh_index)
            self.assertIs(stop_event, stop_event_token)
            return "session-0"

        stop_event_token = cancel_event

        def native_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            timeout_seconds: float,
            stop_event: threading.Event | None = None,
        ) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertIs(stop_event, stop_event_token)
            self.assertEqual("brush", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-0", submesh_payload["session_id"])
            self.assertTrue(submesh_payload["selection_restricts_vertices"])
            self.assertTrue(submesh_payload["sparse_output"])
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertTrue(Path(submesh_payload["selected_edges_binary"]["path"]).is_file())
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "brush",
                "topology_changed": False,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "brush",
                        "topology_changed": False,
                        "changed_vertices": [0, 1],
                        "changed_positions": [[0.0, 0.0, 0.25], [1.0, 0.0, 0.25]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", side_effect=ensure_session),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_brush_selection(
                mesh,
                vertices_by_submesh={},
                edges_by_submesh={0: {(0, 1)}},
                faces_by_submesh={},
                source_indices=(),
                params={"tool": "grab", "drag_delta": (0.0, 0.0, 0.25), "recompute_normals": False},
                stop_event=cancel_event,
            )

        self.assertEqual({0: {0, 1}}, changed)
        self.assertEqual((1.0, 0.0, 0.25), mesh.submeshes[0].vertices[1])

    def test_native_mesh_core_brush_uses_binary_vertex_weights(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            edit_payload = payload["edit"]  # type: ignore[index]
            self.assertIn("vertex_weight_indices_binary", edit_payload)
            self.assertIn("vertex_weights_binary", edit_payload)
            self.assertNotIn("vertex_weights", edit_payload)
            index_path = Path(str(edit_payload["vertex_weight_indices_binary"]["path"]))
            weight_path = Path(str(edit_payload["vertex_weights_binary"]["path"]))
            self.assertTrue(index_path.is_file())
            self.assertTrue(weight_path.is_file())
            indices = array("i")
            indices.frombytes(index_path.read_bytes())
            weights = array("d")
            weights.frombytes(weight_path.read_bytes())
            self.assertEqual([0, 2], list(indices))
            self.assertEqual([0.25, 1.0], list(weights))
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "brush",
                "topology_changed": False,
                "submeshes": [],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_brush_selection(
                mesh,
                vertices_by_submesh={0: {0, 2}},
                edges_by_submesh={},
                faces_by_submesh={},
                source_indices=(),
                params={
                    "tool": "grab",
                    "drag_delta": (0.0, 0.0, 0.25),
                    "vertex_weights": {0: 0.25, 2: 2.0},
                    "recompute_normals": False,
                },
            )

        self.assertEqual({}, changed)

    def test_native_mesh_core_brush_binary_selection_passes_d3d11_descriptors(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            selected_path = Path(temp_dir) / "selected.bin"
            weights_path = Path(temp_dir) / "weights.bin"
            stop_token = threading.Event()
            selected_path.write_bytes(array("i", (0, 2)).tobytes())
            weights_path.write_bytes(array("f", (0.25, 1.0)).tobytes())

            def native_job(
                _binary: Path,
                command: str,
                payload: object,
                *,
                timeout_seconds: float,
                stop_event: threading.Event | None = None,
            ) -> dict[str, object]:
                self.assertEqual("edit-json", command)
                self.assertIs(stop_token, stop_event)
                submesh_payload = payload["submeshes"][0]  # type: ignore[index]
                self.assertEqual("session-0", submesh_payload["session_id"])
                self.assertTrue(submesh_payload["sparse_output"])
                self.assertEqual(str(selected_path), submesh_payload["selected_vertices_binary"]["path"])
                self.assertNotIn("selected_vertices", submesh_payload)
                self.assertNotIn("vertices_binary", submesh_payload)
                self.assertNotIn("faces_binary", submesh_payload)
                edit_payload = payload["edit"]  # type: ignore[index]
                self.assertEqual(str(selected_path), edit_payload["vertex_weight_indices_binary"]["path"])
                self.assertEqual(str(weights_path), edit_payload["vertex_weights_binary"]["path"])
                self.assertNotIn("vertex_weights", edit_payload)
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "brush",
                    "topology_changed": False,
                    "submeshes": [
                        {
                            "index": 0,
                            "action": "brush",
                            "topology_changed": False,
                            "changed_vertices": [0, 2],
                            "changed_positions": [[0.0, 0.0, 0.25], [0.0, 1.0, 1.0]],
                        }
                    ],
                }

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
                patch(
                    "cdmw.modding.mesh_native_core._face_json",
                    side_effect=AssertionError("binary D3D11 stroke path must not rebuild face sidecars"),
                ),
            ):
                changed = mesh_native_core.apply_native_mesh_brush_binary_selection(
                    mesh,
                    selected_vertices_binary_by_submesh={
                        0: {"path": str(selected_path), "count": 2, "components": 1, "type": "i32", "delete_after": True},
                    },
                    vertex_weights_binary_by_submesh={
                        0: {"path": str(weights_path), "count": 2, "components": 1, "type": "f32", "delete_after": True},
                    },
                    params={"tool": "grab", "drag_delta": (0.0, 0.0, 0.25), "recompute_normals": False},
                    stop_event=stop_token,
                )

        self.assertEqual({0: {0, 2}}, changed)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((0.0, 1.0, 1.0), mesh.submeshes[0].vertices[2])

    def test_native_mesh_core_brush_binary_selection_preserves_d3d11_range(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            edit_payload = payload["edit"]  # type: ignore[index]
            self.assertNotIn("vertex_weight_indices_binary", edit_payload)
            self.assertNotIn("vertex_weights_binary", edit_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "brush",
                "topology_changed": False,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "brush",
                        "topology_changed": False,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                        "changed_positions": [[1.0, 0.0, 0.25], [0.0, 1.0, 0.25]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._write_int_binary_payload",
                side_effect=AssertionError("range D3D11 brush path must not write selection sidecars"),
            ),
        ):
            changed = mesh_native_core.apply_native_mesh_brush_binary_selection(
                mesh,
                selected_vertices_binary_by_submesh={0: {"start": 1, "count": 2, "components": 1, "type": "i32_range"}},
                vertex_weights_binary_by_submesh={},
                params={"tool": "grab", "drag_delta": (0.0, 0.0, 0.25), "recompute_normals": False},
            )

        self.assertEqual({0: range(1, 3)}, changed)
        self.assertEqual((1.0, 0.0, 0.25), mesh.submeshes[0].vertices[1])
        self.assertEqual((0.0, 1.0, 0.25), mesh.submeshes[0].vertices[2])

    def test_native_mesh_core_brush_binary_selection_handles_multiple_d3d11_descriptors(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh(two_parts=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            selected_a_path = Path(temp_dir) / "selected_a.bin"
            selected_b_path = Path(temp_dir) / "selected_b.bin"
            selected_a_path.write_bytes(array("i", (0, 2)).tobytes())
            selected_b_path.write_bytes(array("i", (1,)).tobytes())

            def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
                self.assertEqual("edit-json", command)
                submeshes = payload["submeshes"]  # type: ignore[index]
                self.assertEqual(2, len(submeshes))
                self.assertEqual(str(selected_a_path), submeshes[0]["selected_vertices_binary"]["path"])
                self.assertEqual(str(selected_b_path), submeshes[1]["selected_vertices_binary"]["path"])
                self.assertEqual("session-0", submeshes[0]["session_id"])
                self.assertEqual("session-1", submeshes[1]["session_id"])
                for submesh_payload in submeshes:
                    self.assertNotIn("selected_vertices", submesh_payload)
                    self.assertNotIn("vertices_binary", submesh_payload)
                    self.assertNotIn("faces_binary", submesh_payload)
                edit_payload = payload["edit"]  # type: ignore[index]
                self.assertNotIn("vertex_weight_indices_binary", edit_payload)
                self.assertNotIn("vertex_weights_binary", edit_payload)
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "brush",
                    "topology_changed": False,
                    "submeshes": [
                        {
                            "index": 0,
                            "action": "brush",
                            "topology_changed": False,
                            "changed_vertices": [0, 2],
                            "changed_positions": [[0.0, 0.0, 0.25], [0.0, 1.0, 0.25]],
                        },
                        {
                            "index": 1,
                            "action": "brush",
                            "topology_changed": False,
                            "changed_vertices": [1],
                            "changed_positions": [[1.0, 0.0, 0.25]],
                        },
                    ],
                }

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch(
                    "cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh",
                    side_effect=lambda _binary, _mesh, index, **_kwargs: f"session-{index}",
                ),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
                patch(
                    "cdmw.modding.mesh_native_core._face_json",
                    side_effect=AssertionError("multi-descriptor D3D11 stroke path must not rebuild face sidecars"),
                ),
            ):
                changed = mesh_native_core.apply_native_mesh_brush_binary_selection(
                    mesh,
                    selected_vertices_binary_by_submesh={
                        0: {"path": str(selected_a_path), "count": 2, "components": 1, "type": "i32"},
                        1: {"path": str(selected_b_path), "count": 1, "components": 1, "type": "i32"},
                    },
                    vertex_weights_binary_by_submesh={},
                    params={"tool": "grab", "drag_delta": (0.0, 0.0, 0.25), "recompute_normals": False},
                )

        self.assertEqual({0: {0, 2}, 1: {1}}, changed)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((0.0, 1.0, 0.25), mesh.submeshes[0].vertices[2])
        self.assertEqual((1.0, 0.0, 0.25), mesh.submeshes[1].vertices[1])

    def test_brush_binary_selection_failure_does_not_fall_back_to_whole_mesh(self) -> None:
        import cdmw.modding.mesh_edit_ops as mesh_edit_ops

        mesh = _quad_mesh()
        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_brush_binary_selection", return_value=None), patch(
            "cdmw.modding.mesh_edit_ops.apply_native_mesh_brush",
            side_effect=AssertionError("binary descriptor failure must not brush the whole mesh"),
        ), patch(
            "cdmw.modding.mesh_edit_ops.apply_brush_deformation",
            side_effect=AssertionError("binary descriptor failure must not enter Python brush loop"),
        ):
            affected, changed = mesh_edit_ops.apply_mesh_edit_geometry_action(
                mesh,
                MeshEditCommand(
                    "brush",
                    params={
                        "tool": "grab",
                        "native_selected_vertices_binary_by_submesh": {
                            0: {"path": "missing.bin", "count": 1, "components": 1, "type": "i32"},
                        },
                    },
                ),
                MeshEditSelection(),
            )

        self.assertEqual(set(), affected)
        self.assertEqual({}, changed)

    def test_native_mesh_core_selection_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        cancel_event = threading.Event()
        store_payloads: list[object] = []

        def service_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            stop_event: object | None = None,
            timeout_seconds: float,
        ) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            self.assertIs(cancel_event, stop_event)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            stop_event: object | None = None,
            timeout_seconds: float,
        ) -> dict[str, object]:
            self.assertEqual("selection-json", command)
            self.assertIs(cancel_event, stop_event)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("selected_vertices_output_path", submesh_payload)
            self.assertNotIn("vertex_count", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            selected_output_path = Path(str(submesh_payload["selected_vertices_output_path"]))
            selected_output_path.write_bytes(array("i", (0, 1, 2)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection",
                "metrics": {"cpp_ms": 3.25, "io_serialization_ms": 0.5, "python_apply_ms": 0.0, "d3d11_update_ms": 0.0},
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertices_binary": {
                            "path": str(selected_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident selection path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            metrics: dict[str, float] = {}
            selected = mesh_native_core.apply_native_mesh_selection(
                mesh,
                {0: {0}},
                operation="grow",
                stop_event=cancel_event,
                metrics_out=metrics,
            )

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0: {0, 1, 2}}, selected)
        self.assertEqual(3.25, metrics["cpp_ms"])
        self.assertEqual(0.5, metrics["io_serialization_ms"])

    def test_native_mesh_core_selection_forwards_edge_face_and_source_domains(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertTrue(submesh_payload["selected_all_vertices"])
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertNotIn("selected_edges", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            selected_output_path = Path(str(submesh_payload["selected_vertices_output_path"]))
            selected_output_path.write_bytes(array("i", (0, 1, 2, 3)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection",
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertices_binary": {
                            "path": str(selected_output_path),
                            "count": 4,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident selection domain path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            selected = mesh_native_core.apply_native_mesh_selection(
                mesh,
                {0: {0}},
                selected_edges_by_submesh={0: {(0, 1)}},
                selected_faces_by_submesh={0: {1}},
                source_indices=(0,),
                operation="grow",
            )

        self.assertEqual({0: {0, 1, 2, 3}}, selected)

    def test_native_mesh_core_selection_preview_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        cancel_event = threading.Event()
        store_payloads: list[object] = []

        def service_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            stop_event: object | None = None,
            timeout_seconds: float,
        ) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            self.assertIs(cancel_event, stop_event)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["source_face_start"])
            self.assertEqual(2, submesh_payload["source_face_count"])
            self.assertNotIn("source_face_indices_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(
            _binary: Path,
            command: str,
            payload: object,
            *,
            stop_event: object | None = None,
            timeout_seconds: float,
        ) -> dict[str, object]:
            self.assertEqual("selection-preview-json", command)
            self.assertIs(cancel_event, stop_event)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertTrue(submesh_payload["selected_all_vertices"])
            self.assertNotIn("vertex_count", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertNotIn("source_face_indices", submesh_payload)
            self.assertNotIn("source_face_indices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertNotIn("selected_edges", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_preview",
                "groups": [
                    {
                        "source_submesh_index": 0,
                        "source_vertex_indices": [0, 1, 2, 3],
                        "source_edges": [[0, 1]],
                        "source_face_indices": [0],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            groups = mesh_native_core.build_native_mesh_selection_groups(
                mesh,
                vertices_by_submesh={0: {0}},
                edges_by_submesh={0: {(0, 1)}},
                faces_by_submesh={0: {0}},
                source_indices=(0,),
                stop_event=cancel_event,
            )

        self.assertEqual(1, len(store_payloads))
        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0, 1, 2, 3],
                    "source_edges": [[0, 1]],
                    "source_face_indices": [0],
                }
            ],
            groups,
        )

    def test_native_mesh_core_selection_preview_forwards_binary_descriptors(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-preview-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("selection_preview_output_path", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_preview",
                "groups": [
                    {
                        "source_submesh_index": 0,
                        "source_vertex_indices_binary": {
                            "path": "vertices.bin",
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                            "delete_after": True,
                        },
                        "source_edges_binary": {
                            "path": "edges.bin",
                            "count": 1,
                            "components": 2,
                            "type": "i32",
                            "delete_after": True,
                        },
                        "source_face_indices_binary": {
                            "path": "faces.bin",
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                            "delete_after": True,
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            groups = mesh_native_core.build_native_mesh_selection_groups(
                mesh,
                vertices_by_submesh={},
                edges_by_submesh={},
                faces_by_submesh={0: {0}},
            )

        self.assertEqual(1, len(groups))
        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertNotIn("source_vertex_indices", groups[0])
        self.assertEqual(
            {"path": "vertices.bin", "count": 3, "components": 1, "type": "i32", "delete_after": True},
            groups[0]["source_vertex_indices_binary"],
        )
        self.assertEqual(
            {"path": "edges.bin", "count": 1, "components": 2, "type": "i32", "delete_after": True},
            groups[0]["source_edges_binary"],
        )
        self.assertEqual(
            {"path": "faces.bin", "count": 1, "components": 1, "type": "i32", "delete_after": True},
            groups[0]["source_face_indices_binary"],
        )

    def test_native_mesh_core_selection_preview_forwards_source_ranges(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-preview-json", command)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_preview",
                "groups": [
                    {
                        "source_submesh_index": 0,
                        "source_vertex_start": 0,
                        "source_vertex_count": 4,
                        "source_face_start": 0,
                        "source_face_count": 2,
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            groups = mesh_native_core.build_native_mesh_selection_groups(
                mesh,
                vertices_by_submesh={},
                edges_by_submesh={},
                faces_by_submesh={},
                source_indices=(0,),
            )

        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_start": 0,
                    "source_vertex_count": 4,
                    "source_face_start": 0,
                    "source_face_count": 2,
                }
            ],
            groups,
        )

    def test_native_mesh_core_selection_prune_forwards_binary_descriptors(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-prune-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("selection_prune", payload["operation"])  # type: ignore[index]
            self.assertEqual(2, submesh_payload["face_count"])
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertIn("selected_faces_binary", submesh_payload)
            self.assertEqual(2, submesh_payload["selected_faces_binary"]["count"])
            self.assertIn("selected_vertices_output_path", submesh_payload)
            self.assertIn("selected_edges_output_path", submesh_payload)
            self.assertIn("selected_faces_output_path", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertNotIn("selected_edges", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_prune",
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertex_start": 0,
                        "selected_vertex_count": 1,
                        "selected_edges": [[0, 1]],
                        "selected_face_start": 0,
                        "selected_face_count": 1,
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            pruned = mesh_native_core.prune_native_mesh_selection(
                mesh,
                vertices_by_submesh={0: {0, 99}},
                edges_by_submesh={0: {(0, 1), (0, 99)}},
                faces_by_submesh={0: {0, 99}},
                source_indices=(0, 99),
            )

        self.assertEqual(
            {
                "vertices_by_submesh": {0: {0}},
                "edges_by_submesh": {0: {(0, 1)}},
                "faces_by_submesh": {0: {0}},
                "source_indices": (0,),
            },
            pruned,
        )

    def test_native_mesh_core_selection_prune_forwards_current_selection_descriptors(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-prune-json", command)
            self.assertEqual("toggle", payload["selection_operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("toggle", submesh_payload["selection_operation"])
            self.assertEqual(0, submesh_payload["current_selected_vertex_start"])
            self.assertEqual(2, submesh_payload["current_selected_vertex_count"])
            self.assertNotIn("current_selected_vertices_binary", submesh_payload)
            self.assertIn("current_selected_edges_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["current_selected_face_start"])
            self.assertEqual(2, submesh_payload["current_selected_face_count"])
            self.assertNotIn("current_selected_faces_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(2, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_prune",
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertices": [0, 2],
                        "selected_edges": [[1, 3]],
                        "selected_faces": [0],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            pruned = mesh_native_core.prune_native_mesh_selection(
                mesh,
                vertices_by_submesh={0: {1, 2}},
                edges_by_submesh={0: {(0, 1)}},
                faces_by_submesh={0: {1}},
                source_indices=(0,),
                current_vertices_by_submesh={0: {0, 1}},
                current_edges_by_submesh={0: {(0, 1), (1, 3)}},
                current_faces_by_submesh={0: {0, 1}},
                current_source_indices=(0,),
                selection_operation="toggle",
            )

        self.assertEqual(
            {
                "vertices_by_submesh": {0: {0, 2}},
                "edges_by_submesh": {0: {(1, 3)}},
                "faces_by_submesh": {0: {0}},
                "source_indices": (),
            },
            pruned,
        )

    def test_native_mesh_core_selection_prune_forwards_selected_all_vertices_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-prune-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertTrue(submesh_payload["selected_all_vertices"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["current_selected_vertex_start"])
            self.assertEqual(1, submesh_payload["current_selected_vertex_count"])
            self.assertNotIn("current_selected_vertices_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection_prune",
                "submeshes": [{"index": 0, "selected_vertices": [0, 2, 3]}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            pruned = mesh_native_core.prune_native_mesh_selection(
                mesh,
                vertices_by_submesh={},
                edges_by_submesh={},
                faces_by_submesh={},
                selected_all_vertices_by_submesh=(0,),
                current_vertices_by_submesh={0: {1}},
                selection_operation="toggle",
            )

        self.assertEqual({0: {0, 2, 3}}, pruned["vertices_by_submesh"])

    def test_native_mesh_core_selection_prune_combines_current_selection_in_cpp(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        pruned = mesh_native_core.prune_native_mesh_selection(
            mesh,
            vertices_by_submesh={0: {1, 2}},
            edges_by_submesh={0: {(0, 1)}},
            faces_by_submesh={0: {1}},
            source_indices=(0,),
            current_vertices_by_submesh={0: {0, 1}},
            current_edges_by_submesh={0: {(0, 1), (1, 3)}},
            current_faces_by_submesh={0: {0, 1}},
            current_source_indices=(0,),
            selection_operation="toggle",
        )

        self.assertIsNotNone(pruned)
        self.assertEqual({0: {0, 2}}, pruned["vertices_by_submesh"])
        self.assertEqual({0: {(1, 3)}}, pruned["edges_by_submesh"])
        self.assertEqual({0: {0}}, pruned["faces_by_submesh"])
        self.assertEqual((), pruned["source_indices"])

    def test_native_mesh_core_selection_prune_inverts_all_vertices_in_cpp(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        pruned = mesh_native_core.prune_native_mesh_selection(
            mesh,
            vertices_by_submesh={},
            edges_by_submesh={},
            faces_by_submesh={},
            selected_all_vertices_by_submesh=(0,),
            current_vertices_by_submesh={0: {1}},
            selection_operation="toggle",
        )

        self.assertIsNotNone(pruned)
        self.assertEqual({0: {0, 2, 3}}, pruned["vertices_by_submesh"])

    def test_native_mesh_core_selection_prune_rejects_malformed_faces_in_native(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _malformed_face_mesh()
        pruned = mesh_native_core.prune_native_mesh_selection(
            mesh,
            vertices_by_submesh={},
            edges_by_submesh={},
            faces_by_submesh={0: {0, 1, 2}},
        )

        self.assertIsNotNone(pruned)
        self.assertEqual({0: {1}}, pruned["faces_by_submesh"])

    def test_native_mesh_core_delete_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, **kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            faces_output_path.write_bytes(array("i", (0, 1, 2)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "delete",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "delete",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 1,
                            "components": 3,
                            "type": "i32",
                        },
                        "copy_vertex_indices": [0, 1, 2],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, -1],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident topology path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            affected = mesh_native_core.apply_native_mesh_delete(mesh, {0: {1}}, recompute_normals=False)

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0}, affected)
        self.assertEqual(3, mesh.submeshes[0].vertex_count)

    def test_delete_action_passes_native_binary_vertex_selection_to_mesh_core(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="delete-native-binary", mode="edit")
        descriptor = {"path": "selected.bin", "count": 2, "components": 1, "type": "i32"}
        captured: dict[str, object] = {}

        def native_apply(_session_id: str, _edit_payload: Mapping[str, object], **kwargs: object) -> dict[str, object]:
            captured["selection"] = kwargs.get("selection")
            return {
                "status": "ok",
                "topology_changed": True,
                "submesh_count": 1,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "vertex_count": 2, "face_count": 0}],
                "metrics": {"cpp_ms": 1.0},
                "edit_report": {
                    "operation": "delete",
                    "submeshes": [{"index": 0, "vertex_count": 2, "face_count": 0, "changed_vertices": [0, 1]}],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=native_apply),
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_delete", side_effect=AssertionError("legacy delete helper")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete",
                    mode="edit",
                    params={"native_selected_vertices_binary_by_submesh": {0: descriptor}},
                ),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(result.topology_changed)
        selection_payload = captured["selection"]
        self.assertIsInstance(selection_payload, Mapping)
        self.assertEqual({"0": {"selected_vertices_binary": descriptor}}, selection_payload["vertices_by_submesh"])  # type: ignore[index]

    def test_native_mesh_core_delete_keeps_binary_selected_vertices_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            selected_path = Path(temp_dir) / "selected.bin"
            selected_path.write_bytes(array("i", (1, 2)).tobytes())
            original_write_int_payload = mesh_native_core._write_int_binary_payload

            def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
                self.assertEqual("mesh-session-json", command)
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "mesh_session",
                    "session_id": payload["session_id"],  # type: ignore[index]
                    "submesh_count": 1,
                }

            def native_job(_binary: Path, command: str, payload: object, **kwargs: object) -> dict[str, object]:
                self.assertEqual("edit-json", command)
                submesh_payload = payload["submeshes"][0]  # type: ignore[index]
                self.assertIn("session_id", submesh_payload)
                self.assertEqual(
                    {
                        "path": str(selected_path),
                        "count": 2,
                        "components": 1,
                        "type": "i32",
                    },
                    submesh_payload["selected_vertices_binary"],
                )
                self.assertNotIn("selected_vertices", submesh_payload)
                self.assertNotIn("vertices_binary", submesh_payload)
                self.assertNotIn("faces_binary", submesh_payload)
                faces_output_path = Path(str(submesh_payload["faces_output_path"]))
                faces_output_path.write_bytes(array("i", (0, 1, 2)).tobytes())
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "delete",
                    "topology_changed": True,
                    "submeshes": [
                        {
                            "index": 0,
                            "action": "delete",
                            "topology_changed": True,
                            "changed_vertices": [],
                            "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                            "faces_binary": {
                                "path": str(faces_output_path),
                                "count": 1,
                                "components": 3,
                                "type": "i32",
                            },
                            "copy_vertex_indices": [0, 1, 2],
                            "vertex_blends": [],
                            "index_map": [0, 1, 2, -1],
                        }
                    ],
                }

            def write_int_payload(path: object, values: object, *args: object, **kwargs: object) -> dict[str, object]:
                if "selected_vertices" in Path(str(path)).name:
                    raise AssertionError("selected descriptor must not be rewritten")
                return original_write_int_payload(path, values, *args, **kwargs)

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
                patch(
                    "cdmw.modding.mesh_native_core._write_int_binary_payload",
                    side_effect=write_int_payload,
                ),
            ):
                mesh_native_core._clear_native_mesh_core_session_cache()
                affected = mesh_native_core.apply_native_mesh_delete(
                    mesh,
                    {},
                    selected_vertices_binary_by_submesh={
                        0: {"path": str(selected_path), "count": 2, "components": 1, "type": "i32"}
                    },
                    recompute_normals=False,
                )

        self.assertEqual({0}, affected)
        self.assertEqual(3, mesh.submeshes[0].vertex_count)

    def test_native_mesh_core_compact_orphans_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, **kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("compact_orphans", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertIs(submesh_payload["suppress_vertex_remap_report"], True)
            self.assertNotIn("copy_vertex_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_factors_output_path", submesh_payload)
            self.assertNotIn("index_map_output_path", submesh_payload)
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            faces_output_path.write_bytes(array("i", (0, 1, 2, 1, 3, 2)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "compact_orphans",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "compact_orphans",
                        "topology_changed": True,
                        "vertex_remap_report_suppressed": True,
                        "removed_vertices": 0,
                        "changed_vertices": [],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                        ],
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident compact path must not rebuild face sidecars"),
            ),
            patch(
                "cdmw.modding.mesh_native_core._apply_vertex_aligned_topology_result",
                side_effect=AssertionError("resident compact path should not need Python vertex remap"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            result = mesh_native_core.apply_native_mesh_compact_orphans(mesh, (0,), recompute_normals=False)

        self.assertEqual(1, len(store_payloads))
        self.assertIsNotNone(result)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)

    def test_native_mesh_core_fix_winding_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _triangle_mesh()
        mesh.submeshes[0].faces = [(0, 2, 1)]

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("fix_winding", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "fix_winding"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertTrue(submesh_payload["selected_all_faces"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("normals", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "fix_winding",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "fix_winding",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces": [[0, 1, 2]],
                        "copy_vertex_indices": [0, 1, 2],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_fix_winding(mesh, {0}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_fix_winding_edit_json_reverses_faces(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _triangle_mesh()
        mesh.submeshes[0].faces = [(0, 2, 1)]
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_fix_winding(mesh, {0}, recompute_normals=False, timeout_seconds=5.0)
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_fill_holes_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        hole_submesh = SubMesh(
            name="open_tetra",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 3), (1, 2, 3), (2, 0, 3)],
            vertex_count=4,
            face_count=3,
        )
        mesh = ParsedMesh(path="hole.pac", format="pac", submeshes=[hole_submesh], total_vertices=4, total_faces=3)

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("fill_holes", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "fill_holes"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertTrue(submesh_payload["selected_all_faces"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "fill_holes",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "fill_holes",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                        "faces": [[0, 1, 3], [1, 2, 3], [2, 0, 3], [0, 1, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_fill_holes(mesh, {0}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual(4, mesh.submeshes[0].face_count)
        self.assertIn((0, 1, 2), mesh.submeshes[0].faces)

    def test_native_mesh_core_fill_holes_edit_json_adds_missing_triangle(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        hole_submesh = SubMesh(
            name="open_tetra",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 3), (1, 2, 3), (2, 0, 3)],
            vertex_count=4,
            face_count=3,
        )
        mesh = ParsedMesh(path="hole.pac", format="pac", submeshes=[hole_submesh], total_vertices=4, total_faces=3)
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_fill_holes(mesh, {0}, recompute_normals=False, timeout_seconds=5.0)
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual(4, mesh.submeshes[0].face_count)
        self.assertIn((0, 1, 2), mesh.submeshes[0].faces)

    def test_native_mesh_core_fill_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _loose_edge_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("fill", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "fill"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["faces_binary"]["count"])
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "fill",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "fill",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
                        "faces": [[0, 1, 3], [0, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_fill(
                mesh,
                {},
                selected_edges_by_submesh={0: {(0, 1), (1, 3), (2, 3), (0, 2)}},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_fill_edit_json_fills_loose_quad_loop(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _loose_edge_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_fill(
                mesh,
                {},
                selected_edges_by_submesh={0: {(0, 1), (1, 3), (2, 3), (0, 2)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_loop_cut_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _triangle_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("loop_cut", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "loop_cut", "factor": 0.25}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "loop_cut",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "loop_cut",
                        "topology_changed": True,
                        "changed_vertices": [3],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [0.25, 0.0, 0.0],
                        ],
                        "faces": [[0, 3, 2], [3, 1, 2]],
                        "copy_vertex_indices": [0, 1, 2, -1],
                        "vertex_blends": [{"index": 3, "left": 0, "right": 1, "factor": 0.25}],
                        "index_map": [],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_loop_cut(
                mesh,
                {0: {(0, 1)}},
                {"factor": 0.25},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: {3}}, changed)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[3])
        self.assertEqual([(0, 3, 2), (3, 1, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_loop_cut_edit_json_splits_selected_edge_with_factor(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _triangle_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_loop_cut(
                mesh,
                {0: {(0, 1)}},
                {"factor": 0.25},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(3, 4)}, changed)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual(4, len(mesh.submeshes[0].uvs))
        self.assertEqual((0.25, 0.0, 0.0), mesh.submeshes[0].vertices[3])
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[3])
        self.assertEqual([(0, 3, 2), (3, 1, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_edge_split_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("edge_split", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "edge_split"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "edge_split",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "edge_split",
                        "topology_changed": True,
                        "changed_vertices": [4, 5],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 2], [4, 3, 5]],
                        "copy_vertex_indices": [0, 1, 2, 3, 1, 2],
                        "vertex_blends": [],
                        "index_map": [],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_edge_split(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(1, 2)}},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: {4, 5}}, changed)
        self.assertEqual([(0, 1, 2), (4, 3, 5)], mesh.submeshes[0].faces)

    def test_native_mesh_core_edge_split_edit_json_splits_shared_edge(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_edge_split(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(1, 2)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(4, 6)}, changed)
        self.assertEqual(6, mesh.submeshes[0].vertex_count)
        self.assertEqual(6, len(mesh.submeshes[0].uvs))
        self.assertEqual([(0, 1, 2), (4, 3, 5)], mesh.submeshes[0].faces)

    def test_native_mesh_core_merge_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _duplicate_vertex_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("merge", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "merge"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "merge",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "merge",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 2], [1, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3, -1],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_merge(
                mesh,
                {},
                {0: {1, 4}},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({}, changed)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_weld_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _duplicate_vertex_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("weld", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "weld", "threshold": 0.001}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "weld",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "weld",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 2], [1, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3, -1],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_weld(
                mesh,
                {},
                {0: {1, 4}},
                threshold=0.001,
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({}, changed)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_merge_weld_edit_json_compacts_duplicate_vertex(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        merge_mesh = _duplicate_vertex_mesh()
        weld_mesh = _duplicate_vertex_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            merge_affected, merge_changed = mesh_native_core.apply_native_mesh_merge(
                merge_mesh,
                {},
                {0: {1, 4}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
            weld_affected, weld_changed = mesh_native_core.apply_native_mesh_weld(
                weld_mesh,
                {},
                {0: {1, 4}},
                threshold=0.001,
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, merge_affected)
        self.assertEqual({}, merge_changed)
        self.assertEqual(4, merge_mesh.submeshes[0].vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], merge_mesh.submeshes[0].faces)
        self.assertEqual({0}, weld_affected)
        self.assertEqual({}, weld_changed)
        self.assertEqual(4, weld_mesh.submeshes[0].vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], weld_mesh.submeshes[0].faces)

    def test_native_mesh_core_triangulate_display_forwards_raw_display_faces(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("triangulate_display", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "triangulate_display"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual([[0, 1, 3, 2]], submesh_payload["display_faces"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertIs(submesh_payload["suppress_vertex_remap_report"], True)
            self.assertNotIn("copy_vertex_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_factors_output_path", submesh_payload)
            self.assertNotIn("index_map_output_path", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "triangulate_display",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "triangulate_display",
                        "topology_changed": True,
                        "vertex_remap_report_suppressed": True,
                        "changed_vertices": [],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 3], [0, 3, 2]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._apply_vertex_aligned_topology_result",
                side_effect=AssertionError("triangulate display should not need Python vertex remap"),
            ),
        ):
            affected = mesh_native_core.apply_native_mesh_triangulate_display(mesh, {0}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_triangulate_display_edit_json_fans_ngon_faces(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_triangulate_display(
                mesh,
                {0},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_triangulate_display_edit_json_noops_for_triangles(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_triangulate_display(
                mesh,
                {0},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual(set(), affected)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_duplicate_forwards_raw_selection_and_appends_submesh(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("duplicate", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "duplicate"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "duplicate",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "duplicate",
                        "append_submesh": True,
                        "source_index": 0,
                        "name_suffix": " duplicate",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces": [[0, 1, 2]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
                        "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, source_by_new = mesh_native_core.apply_native_mesh_duplicate(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
            )

        self.assertEqual({1}, affected)
        self.assertEqual({1: 0}, source_by_new)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual("quad duplicate", mesh.submeshes[1].name)
        self.assertEqual("mat_a", mesh.submeshes[1].material)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[1].faces)

    def test_native_mesh_core_duplicate_edit_json_appends_selected_face_copy(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, source_by_new = mesh_native_core.apply_native_mesh_duplicate(
                mesh,
                {0: {1}},
                {},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({1}, affected)
        self.assertEqual({1: 0}, source_by_new)
        self.assertEqual(2, len(mesh.submeshes))
        copied = mesh.submeshes[1]
        self.assertEqual("quad duplicate", copied.name)
        self.assertEqual([(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)], copied.vertices)
        self.assertEqual([(0, 2, 1)], copied.faces)
        self.assertEqual([(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], copied.uvs)
        self.assertEqual([(0.0, 0.0, 1.0)] * 3, copied.normals)

    def test_native_mesh_core_mirror_forwards_raw_selection_and_appends_submesh(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("mirror", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "mirror", "axis": "x"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mirror",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "mirror",
                        "append_submesh": True,
                        "source_index": 0,
                        "name_suffix": " mirror",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces": [[0, 2, 1]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
                        "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, source_by_new = mesh_native_core.apply_native_mesh_mirror(
                mesh,
                {},
                {},
                axis="x",
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
            )

        self.assertEqual({1}, affected)
        self.assertEqual({1: 0}, source_by_new)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual("quad mirror", mesh.submeshes[1].name)
        self.assertEqual("mat_a", mesh.submeshes[1].material)
        self.assertEqual([(0, 2, 1)], mesh.submeshes[1].faces)

    def test_native_mesh_core_mirror_edit_json_appends_selected_face_copy(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, source_by_new = mesh_native_core.apply_native_mesh_mirror(
                mesh,
                {0: {1}},
                {},
                axis="x",
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({1}, affected)
        self.assertEqual({1: 0}, source_by_new)
        self.assertEqual(2, len(mesh.submeshes))
        copied = mesh.submeshes[1]
        self.assertEqual("quad mirror", copied.name)
        self.assertEqual([(-1.0, 0.0, 0.0), (-0.0, 1.0, 0.0), (-1.0, 1.0, 0.0)], copied.vertices)
        self.assertEqual([(0, 1, 2)], copied.faces)
        self.assertEqual([(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], copied.uvs)
        self.assertEqual([(0.0, 0.0, 1.0)] * 3, copied.normals)

    def test_native_mesh_core_separate_forwards_raw_selection_and_appends_submesh(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("separate", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "separate"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "separate",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "separate",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
                        "faces": [[0, 2, 1]],
                        "uvs": [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
                        "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                        "copy_vertex_indices": [1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [],
                    },
                    {
                        "index": 0,
                        "action": "separate",
                        "append_submesh": True,
                        "source_index": 0,
                        "name_suffix": " split",
                        "topology_changed": True,
                        "added_vertices": 3,
                        "added_faces": 1,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces": [[0, 1, 2]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
                        "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                    },
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            result = mesh_native_core.apply_native_mesh_separate(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
            )

        self.assertIsNotNone(result)
        self.assertEqual(0, result.source_submesh_index)
        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual([(0, 2, 1)], mesh.submeshes[0].faces)
        self.assertEqual("quad split", mesh.submeshes[1].name)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[1].faces)

    def test_native_mesh_core_separate_edit_json_moves_selected_face_copy(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            result = mesh_native_core.apply_native_mesh_separate(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertIsNotNone(result)
        self.assertEqual(0, result.source_submesh_index)
        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual(2, len(mesh.submeshes))
        source = mesh.submeshes[0]
        moved = mesh.submeshes[1]
        self.assertEqual([(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)], source.vertices)
        self.assertEqual([(0, 2, 1)], source.faces)
        self.assertEqual([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], moved.vertices)
        self.assertEqual([(0, 1, 2)], moved.faces)

    def test_native_mesh_core_dissolve_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("dissolve", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "dissolve"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "dissolve",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "dissolve",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
                        "faces": [[0, 1, 3], [0, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_dissolve(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(1, 2)}},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_dissolve_edit_json_retriangulates_internal_edge(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_dissolve(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(1, 2)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_dissolve_edit_json_deletes_boundary_edge_faces_without_compacting_orphans(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_dissolve(
                mesh,
                {},
                {},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual([(1, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_extrude_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _loose_edge_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("extrude", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "extrude", "offset": [0.0, 0.0, 0.5]}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["faces_binary"]["count"])
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "extrude",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "extrude",
                        "topology_changed": True,
                        "changed_vertices": [4, 5],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.0, 0.0, 0.5],
                            [1.0, 0.0, 0.5],
                        ],
                        "faces": [[0, 1, 5], [0, 5, 4]],
                        "copy_vertex_indices": [0, 1, 2, 3, 0, 1],
                        "vertex_blends": [],
                        "index_map": [],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_extrude(
                mesh,
                {},
                {},
                {"offset": (0.0, 0.0, 0.5)},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: {4, 5}}, changed)
        self.assertEqual([(0, 1, 5), (0, 5, 4)], mesh.submeshes[0].faces)

    def test_native_mesh_core_extrude_edit_json_extrudes_selected_faces(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_extrude(
                mesh,
                {0: {0, 1}},
                {},
                {"offset": (0.0, 0.0, 0.5)},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(4, 8)}, changed)
        self.assertEqual(8, mesh.submeshes[0].vertex_count)
        self.assertEqual(12, mesh.submeshes[0].face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], mesh.submeshes[0].faces[2:4])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in mesh.submeshes[0].faces[4:]))

    def test_native_mesh_core_extrude_edit_json_extrudes_loose_edge(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _loose_edge_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_extrude(
                mesh,
                {},
                {},
                {"offset": (0.0, 0.0, 0.5)},
                selected_edges_by_submesh={0: {(0, 1)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(4, 6)}, changed)
        self.assertEqual(6, mesh.submeshes[0].vertex_count)
        self.assertEqual([(0, 1, 5), (0, 5, 4)], mesh.submeshes[0].faces)
        self.assertEqual((0.0, 0.0), mesh.submeshes[0].uvs[4])
        self.assertEqual((1.0, 0.0), mesh.submeshes[0].uvs[5])

    def test_native_mesh_core_inset_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("inset", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "inset", "amount": 0.5}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_face_start"])
            self.assertEqual(2, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "inset",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "inset",
                        "topology_changed": True,
                        "changed_vertices": [4, 5, 6, 7],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.25, 0.25, 0.0],
                            [0.75, 0.25, 0.0],
                            [0.25, 0.75, 0.0],
                            [0.75, 0.75, 0.0],
                        ],
                        "faces": [
                            [4, 5, 6],
                            [5, 7, 6],
                            [0, 1, 5],
                            [0, 5, 4],
                            [1, 3, 7],
                            [1, 7, 5],
                            [3, 2, 6],
                            [3, 6, 7],
                            [2, 0, 4],
                            [2, 4, 6],
                        ],
                        "copy_vertex_indices": [0, 1, 2, 3, 0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_inset(
                mesh,
                {0: {0, 1}},
                {},
                {"amount": 0.5},
                recompute_normals=False,
            )

        self.assertEqual({0}, affected)
        self.assertEqual({0: {4, 5, 6, 7}}, changed)
        self.assertEqual(8, mesh.submeshes[0].vertex_count)
        self.assertEqual(10, mesh.submeshes[0].face_count)

    def test_native_mesh_core_inset_edit_json_insets_selected_faces(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_inset(
                mesh,
                {0: {0, 1}},
                {},
                {"amount": 0.5},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual({0: range(4, 8)}, changed)
        self.assertEqual(8, mesh.submeshes[0].vertex_count)
        self.assertEqual(10, mesh.submeshes[0].face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], mesh.submeshes[0].faces[:2])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in mesh.submeshes[0].faces[2:]))

    def test_native_mesh_core_inset_edit_json_zero_amount_noops(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected, changed = mesh_native_core.apply_native_mesh_inset(
                mesh,
                {0: {0, 1}},
                {},
                {"amount": 0.0},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual(set(), affected)
        self.assertEqual({}, changed)
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual(2, mesh.submeshes[0].face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_bridge_forwards_edit_json(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _loose_edge_mesh()

        def native_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("bridge", payload["operation"])  # type: ignore[index]
            self.assertEqual({"operation": "bridge"}, payload["edit"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["index"])
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["faces_binary"]["count"])
            self.assertIn("selected_edges_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "bridge",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "bridge",
                        "topology_changed": True,
                        "changed_vertices": [],
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
                        "faces": [[0, 1, 3], [0, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3],
                        "vertex_blends": [],
                        "index_map": [0, 1, 2, 3],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=""),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected = mesh_native_core.apply_native_mesh_bridge(mesh, {0: {(0, 1), (2, 3)}}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_bridge_edit_json_connects_loose_edges(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _loose_edge_mesh()
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            affected = mesh_native_core.apply_native_mesh_bridge(
                mesh,
                {0: {(0, 1), (2, 3)}},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual({0}, affected)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], mesh.submeshes[0].faces)

    def test_native_mesh_core_delete_edit_json_applies_topology_report(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].normals = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)]
        mesh.submeshes[0].tangents = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)]
        mesh.submeshes[0].tangent_signs = [1.0, -1.0, 1.0, -1.0]
        mesh.submeshes[0].bone_indices = [(1,), (2, 3), (4,), (5,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (0.25, 0.75), (1.0,), (1.0,)]
        mesh.submeshes[0].source_vertex_map = [10, 11, 12, 13]
        mesh.submeshes[0].source_vertex_offsets = [100, 110, 120, 130]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("delete", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(1, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertIn("session_id", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            tangent_signs_output_path = Path(str(submesh_payload["tangent_signs_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            self.assertIs(submesh_payload["suppress_vertex_remap_report"], True)
            self.assertNotIn("copy_vertex_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_factors_output_path", submesh_payload)
            self.assertNotIn("index_map_output_path", submesh_payload)
            vertex_data = array("d")
            vertex_data.extend((0.0, 0.0, 0.0))
            vertex_data.extend((1.0, 0.0, 0.0))
            vertex_data.extend((0.0, 1.0, 0.0))
            vertices_output_path.write_bytes(vertex_data.tobytes())
            normal_data = array("d")
            normal_data.extend((7.0, 0.0, 0.0))
            normal_data.extend((0.0, 7.0, 0.0))
            normal_data.extend((0.0, 0.0, 7.0))
            normals_output_path.write_bytes(normal_data.tobytes())
            uv_data = array("d")
            uv_data.extend((0.25, 0.25))
            uv_data.extend((0.75, 0.25))
            uv_data.extend((0.25, 0.75))
            uvs_output_path.write_bytes(uv_data.tobytes())
            tangent_data = array("d")
            tangent_data.extend((9.0, 0.0, 0.0))
            tangent_data.extend((0.0, 9.0, 0.0))
            tangent_data.extend((0.0, 0.0, 9.0))
            tangents_output_path.write_bytes(tangent_data.tobytes())
            tangent_signs_output_path.write_bytes(array("d", (0.5, -0.5, 1.0)).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 2, 0)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (8, 9, 10)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 0.25, 0.75)).tobytes())
            source_map_output_path.write_bytes(array("i", (20, 21, -1)).tobytes())
            source_offsets_output_path.write_bytes(array("i", (200, 210, -1)).tobytes())
            face_data = array("i", (0, 1, 2))
            faces_output_path.write_bytes(face_data.tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "delete",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "delete",
                        "topology_changed": True,
                        "vertex_remap_report_suppressed": True,
                        "changed_vertices": [],
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 3,
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 1,
                            "components": 3,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 3,
                            "components": 3,
                            "type": "f64",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 3,
                            "components": 2,
                            "type": "f64",
                        },
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 3,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangent_signs_binary": {
                            "path": str(tangent_signs_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "f64",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_map_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_offsets_output_path),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", return_value={"status": "ok"}),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._apply_vertex_aligned_topology_result",
                side_effect=AssertionError("native topology report should not need Python vertex remap"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            affected = mesh_native_core.apply_native_mesh_delete(mesh, {0: {1}}, recompute_normals=False)

        self.assertEqual({0}, affected)
        submesh = mesh.submeshes[0]
        self.assertEqual(3, submesh.vertex_count)
        self.assertEqual([(0, 1, 2)], submesh.faces)
        self.assertEqual([(7.0, 0.0, 0.0), (0.0, 7.0, 0.0), (0.0, 0.0, 7.0)], submesh.normals)
        self.assertEqual([(0.25, 0.25), (0.75, 0.25), (0.25, 0.75)], submesh.uvs)
        self.assertEqual([(9.0, 0.0, 0.0), (0.0, 9.0, 0.0), (0.0, 0.0, 9.0)], submesh.tangents)
        self.assertEqual([0.5, -0.5, 1.0], submesh.tangent_signs)
        self.assertEqual([(8,), (9, 10), ()], submesh.bone_indices)
        self.assertEqual([(1.0,), (0.25, 0.75), ()], submesh.bone_weights)
        self.assertEqual([20, 21, -1], submesh.source_vertex_map)
        self.assertEqual([200, 210, -1], submesh.source_vertex_offsets)

    def test_native_mesh_core_topology_edit_recomputes_normals_natively(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        original_normals = [(0.0, 0.0, 0.0)] * 4
        mesh.submeshes[0].normals = original_normals
        commands: list[str] = []
        original_copy_blend = mesh_native_core._copy_blend_tuple_list

        def guarded_copy_blend(values: object, *args: object, **kwargs: object) -> list[tuple[float, ...]]:
            if values is original_normals:
                raise AssertionError("topology normal remap should be skipped before native recompute")
            return original_copy_blend(values, *args, **kwargs)

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            commands.append(command)
            if command == "edit-json":
                self.assertEqual("delete", payload["operation"])  # type: ignore[index]
                self.assertIn("session_id", payload["submeshes"][0])  # type: ignore[index]
                self.assertEqual(1, payload["submeshes"][0]["selected_face_start"])  # type: ignore[index]
                self.assertEqual(1, payload["submeshes"][0]["selected_face_count"])  # type: ignore[index]
                self.assertNotIn("selected_faces_binary", payload["submeshes"][0])  # type: ignore[index]
                self.assertNotIn("vertices_binary", payload["submeshes"][0])  # type: ignore[index]
                self.assertNotIn("vertices", payload["submeshes"][0])  # type: ignore[index]
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "delete",
                    "topology_changed": True,
                    "submeshes": [
                        {
                            "index": 0,
                            "action": "delete",
                            "topology_changed": True,
                            "changed_vertices": [],
                            "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                            "faces": [[0, 1, 2]],
                            "copy_vertex_indices": [0, 1, 2],
                            "vertex_blends": [],
                            "index_map": [0, 1, 2, -1],
                        }
                    ],
                }
            self.assertEqual("recalculate-normals-json", command)
            self.assertEqual("recalculate_normals", payload["operation"])  # type: ignore[index]
            normal_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", normal_payload)
            self.assertNotIn("vertices_binary", normal_payload)
            self.assertNotIn("faces_binary", normal_payload)
            self.assertNotIn("normals_binary", normal_payload)
            self.assertNotIn("vertices", normal_payload)
            self.assertNotIn("faces", normal_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "recalculate_normals",
                "submeshes": [{"index": 0, "normals": [[0.0, 0.0, 1.0]] * 3}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", return_value={"status": "ok"}),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch("cdmw.modding.mesh_native_core._copy_blend_tuple_list", side_effect=guarded_copy_blend),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            affected = mesh_native_core.apply_native_mesh_delete(mesh, {0: {1}})

        self.assertEqual({0}, affected)
        self.assertEqual(["edit-json", "recalculate-normals-json"], commands)
        self.assertEqual([(0.0, 0.0, 1.0)] * 3, mesh.submeshes[0].normals)

    def test_large_native_normal_recompute_blocks_python_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _large_mesh_for_native_fallback_guard()
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core.apply_native_mesh_recalculate_normals", return_value=None),
            patch(
                "cdmw.modding.mesh_native_core.recompute_submesh_normals",
                side_effect=AssertionError("python normal fallback"),
            ),
        ):
            mesh_native_core._recompute_normals_native_or_fallback(mesh, {0}, timeout_seconds=0.1)

        self.assertEqual({"normals.recalculate.blocked": 1}, mesh_native_core.native_mesh_core_fallback_counts())
        event = mesh_native_core.native_mesh_core_fallback_events()[0]
        self.assertEqual("Python normal recompute fallback blocked while native mesh core is available", event["reason"])
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_native_normal_recompute_blocks_small_python_fallback_when_native_available(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core.apply_native_mesh_recalculate_normals", return_value=None),
            patch(
                "cdmw.modding.mesh_native_core.recompute_submesh_normals",
                side_effect=AssertionError("python normal fallback"),
            ),
        ):
            mesh_native_core._recompute_normals_native_or_fallback(mesh, {0}, timeout_seconds=0.1)

        self.assertEqual({"normals.recalculate.blocked": 1}, mesh_native_core.native_mesh_core_fallback_counts())
        event = mesh_native_core.native_mesh_core_fallback_events()[0]
        self.assertEqual("Python normal recompute fallback blocked while native mesh core is available", event["reason"])
        mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_native_mesh_core_weighted_and_flip_normals_use_resident_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        mesh.submeshes[0].normals = [(1.0, 0.0, 0.0)] * 4
        operations: list[str] = []
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("normals_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("recalculate-normals-json", command)
            operation = payload["operation"]  # type: ignore[index]
            operations.append(operation)
            normal_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", normal_payload)
            self.assertNotIn("vertices_binary", normal_payload)
            self.assertNotIn("faces_binary", normal_payload)
            self.assertNotIn("normals_binary", normal_payload)
            self.assertNotIn("vertices", normal_payload)
            self.assertNotIn("faces", normal_payload)
            self.assertNotIn("normals", normal_payload)
            normals_output_path = Path(str(normal_payload["normals_output_path"]))

            def normals_descriptor(values: list[tuple[float, float, float]]) -> dict[str, object]:
                data = array("d")
                for value in values:
                    data.extend(value)
                normals_output_path.write_bytes(data.tobytes())
                return {
                    "path": str(normals_output_path),
                    "count": len(values),
                    "components": 3,
                    "type": "f64",
                }

            changed_vertices_output_path = Path(str(normal_payload["changed_vertices_output_path"]))

            def changed_vertices_descriptor(values: list[int]) -> dict[str, object]:
                data = array("i", values)
                changed_vertices_output_path.write_bytes(data.tobytes())
                return {
                    "path": str(changed_vertices_output_path),
                    "count": len(values),
                    "components": 1,
                    "type": "i32",
                }

            if operation == "flip_normals":
                self.assertIn("faces_output_path", normal_payload)
                self.assertNotIn("preview_vertex_output_path", normal_payload)
                self.assertEqual(0, normal_payload["selected_face_start"])
                self.assertEqual(1, normal_payload["selected_face_count"])
                self.assertNotIn("selected_faces_binary", normal_payload)
                self.assertNotIn("selected_faces", normal_payload)
                flipped_normals = [(0.0, 0.0, -1.0)] * 4
                faces_output_path = Path(str(normal_payload["faces_output_path"]))
                face_data = array("i")
                face_data.extend((0, 2, 1, 1, 3, 2))
                faces_output_path.write_bytes(face_data.tobytes())
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "flip_normals",
                    "submeshes": [
                        {
                            "index": 0,
                            "faces_binary": {
                                "path": str(faces_output_path),
                                "count": 2,
                                "components": 3,
                                "type": "i32",
                            },
                            "normals_binary": normals_descriptor(flipped_normals),
                            "changed_vertices_binary": changed_vertices_descriptor([0, 1, 2, 3]),
                        }
                    ],
                }
            if operation == "recalculate_normals":
                self.assertNotIn("faces_output_path", normal_payload)
                self.assertIn("preview_vertex_output_path", normal_payload)
                recalculated_normals = [(0.0, 0.0, 1.0)] * 4
                return {
                    "status": "ok",
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "recalculate_normals",
                    "submeshes": [
                        {
                            "index": 0,
                            "normals_binary": normals_descriptor(recalculated_normals),
                            "changed_vertices_binary": changed_vertices_descriptor([1, 3]),
                            "preview_vertex_update_group": {
                                "preview_backend": "cdmw_mesh_core",
                                "source_submesh_index": 0,
                                "source_vertex_indices_binary": {
                                    "path": "normal_ids.bin",
                                    "count": 2,
                                    "components": 1,
                                    "type": "i32",
                                    "delete_after": True,
                                },
                                "positions_binary": {
                                    "path": "normal_positions.bin",
                                    "count": 2,
                                    "components": 3,
                                    "type": "f64",
                                    "delete_after": True,
                                },
                                "normals_binary": {
                                    "path": "normal_normals.bin",
                                    "count": 2,
                                    "components": 3,
                                    "type": "f64",
                                    "delete_after": True,
                                },
                                "uvs_binary": {
                                    "path": "normal_uvs.bin",
                                    "count": 2,
                                    "components": 2,
                                    "type": "f64",
                                    "delete_after": True,
                                },
                            },
                        }
                    ],
                }
            self.assertNotIn("faces_output_path", normal_payload)
            self.assertIn("preview_vertex_output_path", normal_payload)
            weighted_normals = [(0.0, 1.0, 0.0)] * 4
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "weighted_normals",
                "submeshes": [
                    {
                        "index": 0,
                        "normals_binary": normals_descriptor(weighted_normals),
                        "changed_vertices_binary": changed_vertices_descriptor([0, 1, 2, 3]),
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident normal path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            recalculated = mesh_native_core.apply_native_mesh_recalculate_normals(mesh, {0}, return_changed_vertices=True)
            preview_group = mesh.submeshes[0].cdmw_native_preview_vertex_update_group
            self.assertNotIn("source_vertex_indices", preview_group)
            self.assertNotIn("positions", preview_group)
            self.assertNotIn("normals", preview_group)
            self.assertEqual(
                {"path": "normal_ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
                preview_group["source_vertex_indices_binary"],
            )
            self.assertEqual(
                {"path": "normal_normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                preview_group["normals_binary"],
            )
            weighted = mesh_native_core.apply_native_mesh_weighted_normals(mesh, {0})
            flipped = mesh_native_core.apply_native_mesh_flip_normals(mesh, {0}, selected_faces_by_submesh={0: {0}})

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0: {1, 3}}, recalculated)
        self.assertEqual({0: {0, 1, 2, 3}}, weighted)
        self.assertEqual({0}, flipped)
        self.assertEqual(["recalculate_normals", "weighted_normals", "flip_normals"], operations)
        self.assertEqual([(0, 2, 1), (1, 3, 2)], mesh.submeshes[0].faces)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, mesh.submeshes[0].normals)

    def test_native_normals_report_trusts_changed_descriptor_without_python_compare(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        normals_path = Path(tempfile.gettempdir()) / f"cdmw-normals-{uuid4().hex}.bin"
        changed_path = Path(tempfile.gettempdir()) / f"cdmw-normal-changed-{uuid4().hex}.bin"
        self.addCleanup(lambda: normals_path.unlink(missing_ok=True))
        self.addCleanup(lambda: changed_path.unlink(missing_ok=True))
        normal_values = array("d")
        for normal in ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)):
            normal_values.extend(normal)
        normals_path.write_bytes(normal_values.tobytes())
        changed_path.write_bytes(array("i", (1,)).tobytes())
        real_vec3 = mesh_native_core._vec3

        def guarded_vec3(value: object, *, fallback: float = 0.0) -> object:
            if isinstance(value, tuple):
                raise AssertionError("native normal report apply must not compare every Python normal")
            return real_vec3(value, fallback=fallback)

        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "recalculate_normals",
            "submeshes": [
                {
                    "index": 0,
                    "normals_binary": {"path": str(normals_path), "count": 4, "components": 3, "type": "f64"},
                    "changed_vertices_binary": {"path": str(changed_path), "count": 1, "components": 1, "type": "i32"},
                }
            ],
        }

        with patch("cdmw.modding.mesh_native_core._vec3", side_effect=guarded_vec3):
            applied = mesh_native_core._apply_recalculate_normals_report(mesh, report, return_changed_vertices=True)

        self.assertEqual({0: {1}}, applied)
        self.assertEqual((0.0, 1.0, 0.0), mesh.submeshes[0].normals[1])

    def test_native_normals_report_accepts_compact_changed_range(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        normals_path = Path(tempfile.gettempdir()) / f"cdmw-normals-{uuid4().hex}.bin"
        self.addCleanup(lambda: normals_path.unlink(missing_ok=True))
        normal_values = array("d")
        for normal in ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)):
            normal_values.extend(normal)
        normals_path.write_bytes(normal_values.tobytes())

        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "recalculate_normals",
            "submeshes": [
                {
                    "index": 0,
                    "normals_binary": {"path": str(normals_path), "count": 4, "components": 3, "type": "f64"},
                    "changed_vertex_start": 1,
                    "changed_vertex_count": 2,
                    "preview_vertex_update_group": {
                        "preview_backend": "cdmw_mesh_core",
                        "source_submesh_index": 0,
                        "source_vertex_start": 1,
                        "source_vertex_count": 2,
                        "positions": [1.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                        "normals": [0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                        "uvs": [],
                    },
                }
            ],
        }

        applied = mesh_native_core._apply_recalculate_normals_report(mesh, report, return_changed_vertices=True)

        self.assertIsInstance(applied[0], range)  # type: ignore[index]
        self.assertEqual(range(1, 3), applied[0])  # type: ignore[index]
        self.assertEqual(1, mesh.submeshes[0].cdmw_native_preview_vertex_update_group["source_vertex_start"])
        self.assertNotIn("changed_vertices_binary", report["submeshes"][0])
        self.assertEqual((0.0, 1.0, 0.0), mesh.submeshes[0].normals[1])

    def test_native_normals_report_empty_changed_range_skips_python_compare(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        normals_path = Path(tempfile.gettempdir()) / f"cdmw-normals-{uuid4().hex}.bin"
        self.addCleanup(lambda: normals_path.unlink(missing_ok=True))
        normal_values = array("d")
        for normal in mesh.submeshes[0].normals:
            normal_values.extend(normal)
        normals_path.write_bytes(normal_values.tobytes())

        real_vec3 = mesh_native_core._vec3

        def guarded_vec3(value: object, *, fallback: float = 0.0) -> object:
            if isinstance(value, tuple):
                raise AssertionError("empty native normal range must not compare every Python normal")
            return real_vec3(value, fallback=fallback)

        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "recalculate_normals",
            "submeshes": [
                {
                    "index": 0,
                    "normals_binary": {"path": str(normals_path), "count": 4, "components": 3, "type": "f64"},
                    "changed_vertex_start": 0,
                    "changed_vertex_count": 0,
                }
            ],
        }

        with patch("cdmw.modding.mesh_native_core._vec3", side_effect=guarded_vec3):
            applied = mesh_native_core._apply_recalculate_normals_report(mesh, report, return_changed_vertices=True)

        self.assertEqual({}, applied)

    def test_native_mesh_core_subdivide_edit_json_blends_vertex_attributes(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.bone_indices = [(0,), (1,), (2,), (3,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        submesh.source_vertex_map = [10, 11, 12, 13]
        submesh.source_vertex_offsets = [100, 110, 120, 130]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("subdivide", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("uvs_binary", submesh_payload)
            self.assertIs(submesh_payload["suppress_vertex_remap_report"], True)
            self.assertNotIn("copy_vertex_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_indices_output_path", submesh_payload)
            self.assertNotIn("vertex_blend_factors_output_path", submesh_payload)
            self.assertNotIn("index_map_output_path", submesh_payload)
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertices_output_path.write_bytes(
                array(
                    "d",
                    (
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                        1.0,
                        1.0,
                        0.0,
                        0.5,
                        0.0,
                        0.0,
                    ),
                ).tobytes()
            )
            faces_output_path.write_bytes(array("i", (0, 4, 2, 4, 1, 2, 1, 3, 2)).tobytes())
            uvs_output_path.write_bytes(array("d", (0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.5, 0.0)).tobytes())
            normals_output_path.write_bytes(array("d", (0.0, 0.0, 1.0) * 5).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 1, 1, 1, 2)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (0, 1, 2, 3, 0, 1)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, 1.0, 0.5, 0.5)).tobytes())
            source_map_output_path.write_bytes(array("i", (10, 11, 12, 13, -1)).tobytes())
            source_offsets_output_path.write_bytes(array("i", (100, 110, 120, 130, -1)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "subdivide",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "subdivide",
                        "topology_changed": True,
                        "vertex_remap_report_suppressed": True,
                        "changed_vertices": [0, 1, 2, 4],
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 3,
                            "components": 3,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 5,
                            "components": 2,
                            "type": "f64",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 6,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 6,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_map_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_offsets_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_subdivide(mesh, {0: {0}}, {}, {}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual({0: {0, 1, 2, 4}}, changed)
        self.assertEqual(5, submesh.vertex_count)
        self.assertEqual((0.5, 0.0), submesh.uvs[4])
        self.assertEqual((0, 1), submesh.bone_indices[4])
        self.assertEqual((0.5, 0.5), submesh.bone_weights[4])
        self.assertEqual(-1, submesh.source_vertex_map[4])
        self.assertEqual(-1, submesh.source_vertex_offsets[4])

    def test_native_mesh_core_subdivide_preview_preserves_source_face_indices(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            result = mesh_native_core.apply_native_mesh_subdivide(
                mesh,
                {0: {0}},
                {},
                {},
                recompute_normals=False,
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(result)
            group = getattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group")
            source_faces_descriptor = group["source_face_indices_binary"]
            source_faces = mesh_native_core._read_i32_binary_report_payload(
                source_faces_descriptor,
                expected_count=int(source_faces_descriptor["count"]),
            )
            source_vertices_descriptor = group["source_vertex_indices_binary"]
            source_vertices = mesh_native_core._read_i32_binary_report_payload(
                source_vertices_descriptor,
                expected_count=int(source_vertices_descriptor["count"]),
            )
        finally:
            mesh_native_core._cleanup_native_preview_delta_paths()
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual([0, 0, 0, 0, 1], source_faces)
        self.assertEqual([0, 1, 2, 3, -1, -1, -1], source_vertices)

    def test_native_mesh_core_edit_json_suppresses_topology_remap_report_when_requested(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        with tempfile.TemporaryDirectory(prefix="cdmw-native-remap-suppression-") as temp_dir:
            root = Path(temp_dir)
            payload = {
                "version": 1,
                "backend": mesh_native_core.NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "subdivide",
                "edit": {
                    "operation": "subdivide",
                    "max_faces_per_submesh": 16,
                    "smooth_strength": 0.0,
                    "smooth_iterations": 1,
                },
                "submeshes": [
                    {
                        "index": 0,
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
                        "faces": [[0, 1, 2], [1, 3, 2]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
                        "normals": [[0.0, 0.0, 1.0]] * 4,
                        "selected_face_start": 0,
                        "selected_face_count": 1,
                        "vertices_output_path": str(root / "vertices.bin"),
                        "faces_output_path": str(root / "faces.bin"),
                        "uvs_output_path": str(root / "uvs.bin"),
                        "normals_output_path": str(root / "normals.bin"),
                        "preview_triangle_output_path": str(root / "preview_triangles.bin"),
                        "suppress_vertex_remap_report": True,
                    }
                ],
            }
            report = mesh_native_core._run_native_mesh_core_job(binary, "edit-json", payload, timeout_seconds=5.0)

        self.assertIsInstance(report, Mapping)
        item = report["submeshes"][0]  # type: ignore[index]
        self.assertIs(item["vertex_remap_report_suppressed"], True)
        self.assertIn("vertices_binary", item)
        self.assertIn("faces_binary", item)
        self.assertIn("uvs_binary", item)
        self.assertIn("normals_binary", item)
        self.assertNotIn("copy_vertex_indices", item)
        self.assertNotIn("copy_vertex_indices_binary", item)
        self.assertNotIn("vertex_blends", item)
        self.assertNotIn("vertex_blend_indices_binary", item)
        self.assertNotIn("vertex_blend_factors_binary", item)
        self.assertNotIn("index_map", item)
        self.assertNotIn("index_map_binary", item)

    def test_native_mesh_core_cleanup_json_suppresses_index_map_report_when_requested(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        with tempfile.TemporaryDirectory(prefix="cdmw-native-cleanup-index-suppression-") as temp_dir:
            root = Path(temp_dir)
            payload = {
                "version": 1,
                "backend": mesh_native_core.NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "cleanup",
                "cleanup": {"threshold": 0.001},
                "submeshes": [
                    {
                        "index": 0,
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 2], [1, 3, 2], [1, 4, 2]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 1.0]],
                        "selected_vertex_start": 0,
                        "selected_vertex_count": 5,
                        "vertices_output_path": str(root / "vertices.bin"),
                        "faces_output_path": str(root / "faces.bin"),
                        "normals_output_path": str(root / "normals.bin"),
                        "uvs_output_path": str(root / "uvs.bin"),
                        "suppress_index_map_report": True,
                    }
                ],
            }
            report = mesh_native_core._run_native_mesh_core_job(binary, "cleanup-json", payload, timeout_seconds=5.0)

        self.assertIsInstance(report, Mapping)
        item = report["submeshes"][0]  # type: ignore[index]
        self.assertIs(item["index_map_report_suppressed"], True)
        self.assertIn("vertices_binary", item)
        self.assertIn("faces_binary", item)
        self.assertIn("normals_binary", item)
        self.assertIn("uvs_binary", item)
        self.assertNotIn("index_map", item)
        self.assertNotIn("index_map_binary", item)

    def test_native_mesh_core_preview_triangle_groups_use_resident_session(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        mesh.submeshes[0].source_vertex_map = [10, 11, 12, 13]
        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            groups = mesh_native_core.build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=(0,),
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(groups)
            group = groups[0]
            source_faces = list(range(int(group["source_face_start"]), int(group["source_face_start"]) + int(group["source_face_count"])))
            source_vertices = list(
                range(int(group["source_vertex_start"]), int(group["source_vertex_start"]) + int(group["source_vertex_count"]))
            )
            indices_descriptor = group["indices_binary"]
            indices = mesh_native_core._read_i32_binary_report_payload(
                indices_descriptor,
                expected_count=int(indices_descriptor["count"]),
            )
        finally:
            mesh_native_core._cleanup_native_preview_delta_paths()
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertEqual([0, 1], source_faces)
        self.assertEqual([10, 11, 12, 13], source_vertices)
        self.assertNotIn("source_face_indices_binary", group)
        self.assertNotIn("source_vertex_indices_binary", group)
        self.assertEqual([0, 1, 2, 1, 3, 2], indices)

    def test_native_mesh_core_preview_triangle_groups_retry_missing_resident_group(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        calls: list[object] = []

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("preview-triangle-groups-json", command)
            calls.append(payload)
            if len(calls) == 1:
                return {"groups": []}
            return {
                "groups": [
                    {
                        "preview_backend": "cdmw_mesh_core",
                        "source_submesh_index": 0,
                        "source_vertex_start": 0,
                        "source_vertex_count": 4,
                        "source_face_start": 0,
                        "source_face_count": 2,
                        "positions": [0.0, 0.0, 0.0] * 4,
                        "normals": [0.0, 0.0, 1.0] * 4,
                        "uvs": [0.0, 0.0] * 4,
                        "indices": [0, 1, 2, 1, 3, 2],
                    }
                ]
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch("cdmw.modding.mesh_native_core._invalidate_native_mesh_session_submeshes") as invalidate,
        ):
            groups = mesh_native_core.build_native_mesh_preview_triangle_groups(mesh, source_indices=(0,))

        self.assertEqual(2, len(calls))
        invalidate.assert_called_once_with(mesh, {0})
        self.assertIsNotNone(groups)
        self.assertEqual(0, groups[0]["source_submesh_index"])  # type: ignore[index]
        self.assertEqual([0, 1, 2, 1, 3, 2], groups[0]["indices"])  # type: ignore[index]

    def test_native_mesh_core_preview_triangle_groups_retry_failed_resident_report(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        calls: list[object] = []

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object] | None:
            self.assertEqual("preview-triangle-groups-json", command)
            calls.append(payload)
            if len(calls) == 1:
                return None
            return {
                "groups": [
                    {
                        "preview_backend": "cdmw_mesh_core",
                        "source_submesh_index": 0,
                        "source_vertex_start": 0,
                        "source_vertex_count": 4,
                        "source_face_start": 0,
                        "source_face_count": 2,
                        "positions": [0.0, 0.0, 0.0] * 4,
                        "normals": [0.0, 0.0, 1.0] * 4,
                        "uvs": [0.0, 0.0] * 4,
                        "indices": [0, 1, 2, 1, 3, 2],
                    }
                ]
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch("cdmw.modding.mesh_native_core._invalidate_native_mesh_session_submeshes") as invalidate,
        ):
            groups = mesh_native_core.build_native_mesh_preview_triangle_groups(mesh, source_indices=(0,))

        self.assertEqual(2, len(calls))
        invalidate.assert_called_once_with(mesh, (0,))
        self.assertIsNotNone(groups)
        self.assertEqual(0, groups[0]["source_submesh_index"])  # type: ignore[index]
        self.assertEqual([0, 1, 2, 1, 3, 2], groups[0]["indices"])  # type: ignore[index]

    def test_native_mesh_core_preview_vertex_update_json_fallback_uses_source_range(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        report = mesh_native_core._run_native_mesh_core_job(
            binary,
            "preview-vertex-update-groups-json",
            {
                "version": 1,
                "backend": "cdmw_mesh_core_0.1",
                "operation": "preview_vertex_update_groups",
                "submeshes": [
                    {
                        "index": 0,
                        "source_submesh_index": 0,
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                    }
                ],
            },
            timeout_seconds=5.0,
        )

        self.assertIsNotNone(report)
        group = report["groups"][0]  # type: ignore[index]
        self.assertEqual(1, group["source_vertex_start"])  # type: ignore[index]
        self.assertEqual(2, group["source_vertex_count"])  # type: ignore[index]
        self.assertNotIn("source_vertex_indices", group)
        self.assertNotIn("source_vertex_indices_binary", group)
        self.assertEqual([1.0, 0.0, 0.0, 1.0, 1.0, 0.0], group["positions"])  # type: ignore[index]

    def test_native_mesh_core_preview_vertex_update_remaps_source_vertex_map(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        report = mesh_native_core._run_native_mesh_core_job(
            binary,
            "preview-vertex-update-groups-json",
            {
                "version": 1,
                "backend": "cdmw_mesh_core_0.1",
                "operation": "preview_vertex_update_groups",
                "submeshes": [
                    {
                        "index": 0,
                        "source_submesh_index": 0,
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "source_vertex_map_start": 10,
                        "source_vertex_map_count": 4,
                        "changed_vertex_start": 1,
                        "changed_vertex_count": 2,
                    }
                ],
            },
            timeout_seconds=5.0,
        )

        self.assertIsNotNone(report)
        group = report["groups"][0]  # type: ignore[index]
        self.assertEqual(11, group["source_vertex_start"])  # type: ignore[index]
        self.assertEqual(2, group["source_vertex_count"])  # type: ignore[index]
        self.assertNotIn("source_vertex_indices", group)
        self.assertNotIn("source_vertex_indices_binary", group)

    def test_native_mesh_core_preview_vertex_update_forwards_changed_vertices_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        with tempfile.TemporaryDirectory() as temp_dir:
            changed_path = Path(temp_dir) / "changed.bin"
            with changed_path.open("wb") as handle:
                array("i", (1, 3)).tofile(handle)
            descriptor = {"path": str(changed_path), "count": 2, "components": 1, "type": "i32", "delete_after": True}
            captured: dict[str, object] = {}

            def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
                self.assertEqual("preview-vertex-update-groups-json", command)
                captured["payload"] = payload
                return {
                    "groups": [
                        {
                            "preview_backend": "cdmw_mesh_core",
                            "source_submesh_index": 0,
                            "source_vertex_indices_binary": descriptor,
                            "positions": [1.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                            "normals": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
                            "uvs": [1.0, 0.0, 1.0, 1.0],
                        }
                    ]
                }

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
                patch("cdmw.modding.mesh_native_core._write_int_binary_payload", side_effect=AssertionError("python id sidecar write")),
            ):
                groups = mesh_native_core.build_native_mesh_preview_vertex_update_groups(
                    mesh,
                    {0: {"changed_vertices_binary": descriptor}},
                )

        payload = captured["payload"]
        self.assertIsInstance(payload, dict)
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        self.assertEqual(descriptor, submesh_payload["changed_vertices_binary"])
        self.assertNotIn("changed_vertices", submesh_payload)
        self.assertNotIn("changed_vertex_start", submesh_payload)
        self.assertEqual(descriptor, groups[0]["source_vertex_indices_binary"])  # type: ignore[index]

    def test_native_mesh_core_full_preview_vertex_update_json_fallback_uses_source_range(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        report = mesh_native_core._run_native_mesh_core_job(
            binary,
            "preview-vertex-update-groups-json",
            {
                "version": 1,
                "backend": "cdmw_mesh_core_0.1",
                "operation": "preview_vertex_update_groups",
                "submeshes": [
                    {
                        "index": 0,
                        "source_submesh_index": 0,
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "changed_all_vertices": True,
                    }
                ],
            },
            timeout_seconds=5.0,
        )

        self.assertIsNotNone(report)
        group = report["groups"][0]  # type: ignore[index]
        self.assertEqual(0, group["source_vertex_start"])  # type: ignore[index]
        self.assertEqual(4, group["source_vertex_count"])  # type: ignore[index]
        self.assertNotIn("source_vertex_indices", group)
        self.assertNotIn("source_vertex_indices_binary", group)
        self.assertEqual(12, len(group["positions"]))  # type: ignore[arg-type,index]

    def test_native_mesh_core_transform_preview_source_ids_use_range_or_binary(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        vertices = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            first_changed = str(Path(temp_dir) / "first_changed.bin")
            second_changed = str(Path(temp_dir) / "second_changed.bin")
            report = mesh_native_core._run_native_mesh_core_job(
                binary,
                "transform-json",
                {
                    "version": 1,
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "transform",
                    "transform": {
                        "translate": [0.0, 0.0, 1.0],
                        "scale": [1.0, 1.0, 1.0],
                        "rotate": [0.0, 0.0, 0.0],
                        "pivot": [0.0, 0.0, 0.0],
                    },
                    "submeshes": [
                        {
                            "index": 0,
                            "vertices": vertices,
                            "faces": [[0, 1, 2], [1, 3, 2]],
                            "source_vertex_map_start": 10,
                            "source_vertex_map_count": 4,
                            "selected_vertex_start": 1,
                            "selected_vertex_count": 2,
                            "changed_vertices_output_path": first_changed,
                        },
                        {
                            "index": 1,
                            "vertices": vertices,
                            "faces": [[0, 1, 2], [1, 3, 2]],
                            "source_vertex_map_start": 20,
                            "source_vertex_map_count": 4,
                            "selected_vertices": [0, 2],
                            "changed_vertices_output_path": second_changed,
                        },
                    ],
                },
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(report)
            groups = {
                int(item["index"]): item["preview_vertex_update_group"]  # type: ignore[index]
                for item in report["submeshes"]  # type: ignore[index]
            }
            range_group = groups[0]
            self.assertEqual(11, range_group["source_vertex_start"])  # type: ignore[index]
            self.assertEqual(2, range_group["source_vertex_count"])  # type: ignore[index]
            self.assertNotIn("source_vertex_indices", range_group)
            self.assertNotIn("source_vertex_indices_binary", range_group)
            binary_group = groups[1]
            self.assertNotIn("source_vertex_indices", binary_group)
            self.assertNotIn("source_vertex_start", binary_group)
            source_descriptor = binary_group["source_vertex_indices_binary"]  # type: ignore[index]
            self.assertEqual(2, source_descriptor["count"])  # type: ignore[index]
            self.assertEqual([20, 22], mesh_native_core._read_i32_binary_report_payload(source_descriptor, expected_count=2))

    def test_native_mesh_core_split_edit_json_copies_vertex_attributes(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.source_vertex_map = [10, 11, 12, 13]
        submesh.source_vertex_offsets = [100, 110, 120, 130]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("edit-json", command)
            self.assertEqual("split", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["selected_face_start"])
            self.assertEqual(1, submesh_payload["selected_face_count"])
            self.assertNotIn("selected_faces_binary", submesh_payload)
            self.assertNotIn("selected_faces", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "split",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "action": "split",
                        "topology_changed": True,
                        "changed_vertices": [4, 5],
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 4, 5], [1, 3, 2]],
                        "copy_vertex_indices": [0, 1, 2, 3, 1, 2],
                        "vertex_blends": [],
                        "index_map": [],
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            affected, changed = mesh_native_core.apply_native_mesh_split(mesh, {0: {0}}, {}, {}, recompute_normals=False)

        self.assertEqual({0}, affected)
        self.assertEqual({0: {4, 5}}, changed)
        self.assertEqual(6, submesh.vertex_count)
        self.assertEqual([(0, 4, 5), (1, 3, 2)], submesh.faces)
        self.assertEqual((1.0, 0.0), submesh.uvs[4])
        self.assertEqual((0.0, 1.0), submesh.uvs[5])
        self.assertEqual([10, 11, 12, 13, 11, 12], submesh.source_vertex_map)
        self.assertEqual([100, 110, 120, 130, 110, 120], submesh.source_vertex_offsets)

    def test_native_mesh_core_delete_edit_json_reports_source_map_and_offsets_as_ranges(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = mesh_native_core._run_native_mesh_core_job(
                binary,
                "edit-json",
                {
                    "version": 1,
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "delete",
                    "edit": {"operation": "delete"},
                    "submeshes": [
                        {
                            "index": 0,
                            "vertices": [
                                [0.0, 0.0, 0.0],
                                [1.0, 0.0, 0.0],
                                [0.0, 1.0, 0.0],
                                [1.0, 1.0, 0.0],
                            ],
                            "faces": [[0, 1, 2], [1, 3, 2]],
                            "source_vertex_map_start": 10,
                            "source_vertex_map_count": 4,
                            "source_vertex_offsets_start": 100,
                            "source_vertex_offsets_count": 4,
                            "source_vertex_offsets_stride": 10,
                            "selected_face_start": 0,
                            "selected_face_count": 1,
                            "vertices_output_path": str(root / "vertices.bin"),
                            "faces_output_path": str(root / "faces.bin"),
                            "source_vertex_map_output_path": str(root / "source-map.bin"),
                            "source_vertex_offsets_output_path": str(root / "source-offsets.bin"),
                        }
                    ],
                },
                timeout_seconds=5.0,
            )

        self.assertIsNotNone(report)
        item = report["submeshes"][0]  # type: ignore[index]
        self.assertEqual(11, item["source_vertex_map_start"])  # type: ignore[index]
        self.assertEqual(3, item["source_vertex_map_count"])  # type: ignore[index]
        self.assertNotIn("source_vertex_map_binary", item)
        self.assertEqual(110, item["source_vertex_offsets_start"])  # type: ignore[index]
        self.assertEqual(3, item["source_vertex_offsets_count"])  # type: ignore[index]
        self.assertEqual(10, item["source_vertex_offsets_stride"])  # type: ignore[index]
        self.assertNotIn("source_vertex_offsets_binary", item)

    def test_native_mesh_core_optimization_report_invokes_meshoptimizer(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        native_report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "optimize",
            "optimization_backend": "meshoptimizer",
            "topology_changed": True,
            "totals": {
                "input_vertex_count": 4,
                "referenced_vertex_count": 3,
                "input_index_count": 6,
                "output_index_count": 3,
                "input_triangle_count": 2,
                "output_triangle_count": 1,
            },
            "submeshes": [{"index": 0, "faces": [[0, 1, 2]]}],
        }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("optimize-json", command)
            self.assertEqual("optimize", payload["operation"])  # type: ignore[index]
            self.assertEqual(0.5, payload["optimize"]["simplify_ratio"])  # type: ignore[index]
            self.assertEqual(0.02, payload["optimize"]["target_error"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertEqual(4, submesh_payload["vertices_binary"]["count"])
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertTrue(Path(submesh_payload["faces_binary"]["path"]).is_file())
            self.assertEqual(15.0, timeout_seconds)
            return native_report

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            report = mesh_native_core.native_mesh_optimization_report(mesh, {0}, simplify_ratio=0.5, target_error=0.02)

        self.assertEqual(native_report, report)

    def test_native_mesh_core_optimization_report_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []
        native_report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "optimize",
            "optimization_backend": "meshoptimizer",
            "topology_changed": False,
            "totals": {
                "input_vertex_count": 4,
                "referenced_vertex_count": 4,
                "input_index_count": 6,
                "output_index_count": 6,
                "input_triangle_count": 2,
                "output_triangle_count": 2,
            },
            "submeshes": [{"index": 0, "faces": [[0, 1, 2], [1, 3, 2]]}],
        }

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("optimize-json", command)
            self.assertEqual("optimize", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertNotIn("vertices_binary", submesh_payload)
            self.assertNotIn("faces_binary", submesh_payload)
            self.assertEqual(0.5, payload["optimize"]["simplify_ratio"])  # type: ignore[index]
            self.assertEqual(0.02, payload["optimize"]["target_error"])  # type: ignore[index]
            return native_report

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident optimize path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            report = mesh_native_core.native_mesh_optimization_report(mesh, {0}, simplify_ratio=0.5, target_error=0.02)

        self.assertEqual(1, len(store_payloads))
        self.assertEqual(native_report, report)

    def test_native_mesh_core_jobs_use_persistent_service_by_default(self) -> None:
        from cdmw.modding import mesh_native_core

        case = self

        class FakeService:
            def __init__(self) -> None:
                self.calls: list[tuple[str, Path, Path]] = []

            def run_job(self, command: str, job_path: Path, report_path: Path, *, timeout_seconds: float) -> None:
                self.calls.append((command, job_path, report_path))
                case.assertEqual("selection-json", command)
                case.assertTrue(job_path.is_file())
                case.assertEqual(5.0, timeout_seconds)
                report_path.write_text(
                    '{"status":"ok","backend":"cdmw_mesh_core_0.1","operation":"selection","submeshes":[]}',
                    encoding="utf-8",
                )

        fake_service = FakeService()
        with (
            patch("cdmw.modding.mesh_native_core._get_native_mesh_core_service", return_value=fake_service),
            patch("cdmw.modding.mesh_native_core.run_process_with_cancellation") as run_process,
        ):
            report = mesh_native_core._run_native_mesh_core_job(
                Path("native.exe"),
                "selection-json",
                {"operation": "selection", "submeshes": []},
                timeout_seconds=5.0,
            )

        self.assertEqual("ok", report["status"])
        self.assertEqual(1, len(fake_service.calls))
        run_process.assert_not_called()

    def test_native_mesh_core_jobs_pass_stop_event_to_service_path(self) -> None:
        from cdmw.modding import mesh_native_core

        stop_event = threading.Event()
        case = self

        class FakeService:
            def run_job(self, command: str, job_path: Path, report_path: Path, **kwargs: object) -> None:
                case.assertEqual("selection-json", command)
                case.assertIs(stop_event, kwargs["stop_event"])
                report_path.write_text(
                    '{"status":"ok","backend":"cdmw_mesh_core_0.1","operation":"selection","submeshes":[]}',
                    encoding="utf-8",
                )

        with (
            patch("cdmw.modding.mesh_native_core._get_native_mesh_core_service", return_value=FakeService()) as get_service,
            patch("cdmw.modding.mesh_native_core.run_process_with_cancellation") as run_process,
        ):
            report = mesh_native_core._run_native_mesh_core_job(
                Path("native.exe"),
                "selection-json",
                {"operation": "selection", "submeshes": []},
                stop_event=stop_event,
                timeout_seconds=5.0,
            )

        self.assertEqual("ok", report["status"])
        self.assertEqual(1, get_service.call_count)
        run_process.assert_not_called()

    def test_native_editor_session_cancel_marks_service_session_not_ready(self) -> None:
        from cdmw.models import RunCancelled

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-cancel-state", mode="edit")
        session = service._sessions[view.session_id]

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch(
                "cdmw.services.mesh_service.apply_native_mesh_editor_session",
                side_effect=RunCancelled("Native mesh-core job cancelled."),
            ) as apply_native,
            patch("cdmw.services.mesh_service.select_native_mesh_editor_session") as select_native,
        ):
            with self.assertRaises(RunCancelled):
                service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "subdivide",
                        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                        mode="edit",
                    ),
                )

        self.assertFalse(session.native_editor_session_ready)
        apply_native.assert_called_once()
        select_native.assert_not_called()

    def test_uv_edit_invalidates_generated_tangents_and_restores_export_warning(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="tangent-invalidate", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        before_edit = service.validate_export(view.session_id, available_textures=("a.dds",))

        edited = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                params={"offset": (0.25, 0.0)},
            ),
        )
        submesh = service.working_mesh(view.session_id).submeshes[0]
        after_edit = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertNotIn("missing_tangents", {issue.code for issue in before_edit.warnings})
        self.assertTrue(edited.ok)
        self.assertEqual([], submesh.tangents)
        self.assertTrue(any("Invalidated tangents" in message for message in edited.diagnostics))
        self.assertIn("missing_tangents", {issue.code for issue in after_edit.warnings})

    def test_sharpen_soften_and_copy_normals_are_service_routed(self) -> None:
        service = MeshService()
        sharp_view = service.open_edit_session(_bent_two_face_mesh(), session_id="normal-sharpen", mode="edit")

        sharp = service.apply_command(
            sharp_view.session_id,
            MeshEditCommand("sharpen_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (1,)})),
        )
        sharp_submesh = service.working_mesh(sharp_view.session_id).submeshes[0]

        self.assertTrue(sharp.ok)
        self.assertEqual((0,), sharp.affected_submesh_indices)
        self.assertEqual({0, 1, 3}, _changed_vertices_as_set(sharp))
        self.assertEqual((0.0, -1.0, 0.0), sharp_submesh.normals[0])
        self.assertEqual((0.0, 0.0, 1.0), sharp_submesh.normals[2])

        soften = service.apply_command(
            sharp_view.session_id,
            MeshEditCommand("soften_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(soften.ok)
        self.assertEqual((0,), soften.affected_submesh_indices)
        sharp_submesh = service.working_mesh(sharp_view.session_id).submeshes[0]
        self.assertNotEqual((0.0, -1.0, 0.0), sharp_submesh.normals[0])

        weighted_mesh = _bent_two_face_mesh()
        weighted_mesh.submeshes[0].normals = [(1.0, 0.0, 0.0)] * 4
        weighted_view = service.open_edit_session(weighted_mesh, session_id="normal-weighted", mode="edit")
        weighted = service.apply_command(
            weighted_view.session_id,
            MeshEditCommand("weighted_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(weighted.ok)
        self.assertEqual((0,), weighted.affected_submesh_indices)
        self.assertIn(0, dict(weighted.changed_vertices_by_submesh))
        weighted_submesh = service.working_mesh(weighted_view.session_id).submeshes[0]
        self.assertNotEqual((1.0, 0.0, 0.0), weighted_submesh.normals[0])

        copy_mesh = _quad_mesh()
        copy_mesh.submeshes[0].normals = [(1.0, 0.0, 0.0)] * 4
        copy_view = service.open_edit_session(copy_mesh, session_id="normal-copy", mode="edit")
        copied = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("copy_normals", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"source_mesh": _quad_mesh()}),
        )

        self.assertTrue(copied.ok)
        self.assertEqual((0,), copied.affected_submesh_indices)
        copy_submesh = service.working_mesh(copy_view.session_id).submeshes[0]
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, copy_submesh.normals)

    def test_recalculate_normals_requires_explicit_selection_for_whole_part(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-normal-recalc", mode="edit")
        service.working_mesh(empty_view.session_id).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4

        empty = service.apply_command(empty_view.session_id, MeshEditCommand("recalculate_normals"))

        empty_submesh = service.working_mesh(empty_view.session_id).submeshes[0]
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, empty_submesh.normals)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)

        stale_edge_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-normal-recalc", mode="edit")
        stale_edge_submesh = service.working_mesh(stale_edge_view.session_id).submeshes[0]
        stale_edge_submesh.normals = [(0.0, 0.0, -1.0)] * 4
        stale_edge = service.apply_command(
            stale_edge_view.session_id,
            MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        self.assertTrue(stale_edge.ok)
        self.assertEqual((), stale_edge.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, stale_edge_submesh.normals)
        self.assertEqual(0, service.session_view(stale_edge_view.session_id).revision)

        source_mesh = _quad_mesh()
        source_mesh.submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        source_view = service.open_edit_session(source_mesh, session_id="source-normal-recalc", mode="edit")
        source_submesh = service.working_mesh(source_view.session_id).submeshes[0]
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        source_submesh = service.working_mesh(source_view.session_id).submeshes[0]
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, source_submesh.normals)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)

    def test_flip_normals_can_target_selected_face_only(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="face-normal-flip", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertFalse(result.topology_changed)
        self.assertEqual([(0, 2, 1), (1, 3, 2)], submesh.faces)
        self.assertEqual(1, service.session_view(view.session_id).revision)

    def test_flip_normals_requires_explicit_selection_for_whole_part(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-normal-flip", mode="edit")

        empty = service.apply_command(empty_view.session_id, MeshEditCommand("flip_normals"))

        empty_submesh = service.working_mesh(empty_view.session_id).submeshes[0]
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], empty_submesh.faces)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)

        source_view = service.open_edit_session(_quad_mesh(), session_id="source-normal-flip", mode="edit")
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        source_submesh = service.working_mesh(source_view.session_id).submeshes[0]
        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        self.assertEqual([(0, 2, 1), (1, 2, 3)], source_submesh.faces)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)

    def test_material_copy_preserves_authority_route_metadata(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "source_authority",
                    "texture": "source_authority.dds",
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

        target = service.working_mesh(view.session_id).submeshes[1]
        self.assertTrue(copied.ok)
        self.assertEqual("source_authority", target.material)
        self.assertEqual("source_authority.dds", target.texture)
        self.assertEqual("runtime_xml", getattr(target, "cdmw_material_authority_profile"))
        self.assertEqual("runtime_xml_preserve", getattr(target, "cdmw_material_authority_contract"))
        self.assertEqual("ready", getattr(target, "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(target, "preview_native_material_overrides"))

    def test_material_copy_clears_stale_target_route_metadata(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy-clear", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(1,)),
                params={
                    "material": "routed_target",
                    "texture": "routed_target.dds",
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

        target = service.working_mesh(view.session_id).submeshes[1]
        self.assertTrue(copied.ok)
        self.assertEqual("mat_a", target.material)
        self.assertEqual("a.dds", target.texture)
        self.assertFalse(hasattr(target, "cdmw_material_authority_profile"))
        self.assertFalse(hasattr(target, "cdmw_material_authority_contract"))
        self.assertFalse(hasattr(target, "cdmw_material_route_status"))
        self.assertFalse(hasattr(target, "preview_native_material_overrides"))

    def test_plain_material_assign_clears_stale_route_metadata_and_overrides(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="material-assign-clear", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=selection,
                params={
                    "material": "routed",
                    "texture": "routed.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2, "metalness": 0.6},
                },
            ),
        )
        plain = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=selection,
                params={"material": "plain", "texture": "plain.dds"},
            ),
        )

        target = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(plain.ok)
        self.assertEqual((0,), plain.affected_submesh_indices)
        self.assertEqual("plain", target.material)
        self.assertEqual("plain.dds", target.texture)
        self.assertFalse(hasattr(target, "cdmw_material_authority_profile"))
        self.assertFalse(hasattr(target, "cdmw_material_authority_contract"))
        self.assertFalse(hasattr(target, "cdmw_material_route_status"))
        self.assertFalse(hasattr(target, "preview_native_material_overrides"))

    def test_material_assign_can_target_selected_faces_by_splitting_material_part(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="face-material-assign", mode="edit")

        assigned = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={
                    "material": "face_material",
                    "texture": "face.dds",
                    "material_profile": "runtime_xml",
                    "native_material_overrides": {"roughness": 0.4},
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(assigned.ok)
        self.assertTrue(assigned.topology_changed)
        self.assertEqual((0, 1), assigned.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(1, mesh.submeshes[0].face_count)
        self.assertEqual(1, mesh.submeshes[1].face_count)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("face_material", mesh.submeshes[1].material)
        self.assertEqual("face.dds", mesh.submeshes[1].texture)
        self.assertEqual("runtime_xml", getattr(mesh.submeshes[1], "cdmw_material_authority_profile"))
        self.assertEqual({"roughness": 0.4}, getattr(mesh.submeshes[1], "preview_native_material_overrides"))

    def test_material_copy_can_target_selected_faces_by_splitting_material_part(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="face-material-copy", mode="edit")

        service.apply_command(
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
                selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}),
                params={"source_submesh_index": 0},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(copied.ok)
        self.assertTrue(copied.topology_changed)
        self.assertEqual((1, 2), copied.affected_submesh_indices)
        self.assertEqual(3, len(mesh.submeshes))
        self.assertEqual(1, mesh.submeshes[1].face_count)
        self.assertEqual(1, mesh.submeshes[2].face_count)
        self.assertEqual("mat_b", mesh.submeshes[1].material)
        self.assertEqual("source_authority", mesh.submeshes[2].material)
        self.assertEqual("source.dds", mesh.submeshes[2].texture)
        self.assertEqual("runtime_xml", getattr(mesh.submeshes[2], "cdmw_material_authority_profile"))
        self.assertEqual("ready", getattr(mesh.submeshes[2], "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(mesh.submeshes[2], "preview_native_material_overrides"))

    def test_duplicate_preserves_material_route_metadata_on_face_copy(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-material-route", mode="edit")

        assigned = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "source_authority",
                    "texture": "source_authority.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2},
                },
            ),
        )
        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        source = mesh.submeshes[0]
        copied = mesh.submeshes[1]
        self.assertTrue(assigned.ok)
        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual((1,), duplicated.affected_submesh_indices)
        self.assertEqual("source_authority", copied.material)
        self.assertEqual("source_authority.dds", copied.texture)
        self.assertEqual(getattr(source, "cdmw_material_authority_profile"), getattr(copied, "cdmw_material_authority_profile"))
        self.assertEqual(getattr(source, "cdmw_material_authority_contract"), getattr(copied, "cdmw_material_authority_contract"))
        self.assertEqual(getattr(source, "cdmw_material_route_status"), getattr(copied, "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(copied, "preview_native_material_overrides"))

    def test_duplicate_and_mirror_require_explicit_selection_or_source_target(self) -> None:
        service = MeshService()

        duplicate_empty_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-empty-target", mode="edit")
        duplicate_empty = service.apply_command(duplicate_empty_view.session_id, MeshEditCommand("duplicate"))
        self.assertTrue(duplicate_empty.ok)
        self.assertFalse(duplicate_empty.topology_changed)
        self.assertEqual((), duplicate_empty.affected_submesh_indices)
        self.assertEqual(1, service.session_view(duplicate_empty_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(duplicate_empty_view.session_id).revision)

        invalid_face_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-invalid-face-target", mode="edit")
        invalid_face = service.apply_command(
            invalid_face_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)})),
        )
        self.assertTrue(invalid_face.ok)
        self.assertFalse(invalid_face.topology_changed)
        self.assertEqual((), invalid_face.affected_submesh_indices)
        self.assertEqual(1, service.session_view(invalid_face_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(invalid_face_view.session_id).revision)

        invalid_all_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-invalid-all-target", mode="edit")
        invalid_all = service.apply_command(
            invalid_all_view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (99,)}, source_indices=(99,)),
                params={"all": True},
            ),
        )
        self.assertTrue(invalid_all.ok)
        self.assertFalse(invalid_all.topology_changed)
        self.assertEqual((), invalid_all.affected_submesh_indices)
        self.assertEqual(1, service.session_view(invalid_all_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(invalid_all_view.session_id).revision)

        duplicate_all_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-all-target", mode="edit")
        duplicate_all = service.apply_command(
            duplicate_all_view.session_id,
            MeshEditCommand("duplicate", params={"all": True}),
        )
        self.assertTrue(duplicate_all.ok)
        self.assertFalse(duplicate_all.topology_changed)
        self.assertEqual((), duplicate_all.affected_submesh_indices)
        self.assertEqual(1, service.session_view(duplicate_all_view.session_id).submesh_count)

        duplicate_source_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-source-target", mode="edit")
        duplicate_source = service.apply_command(
            duplicate_source_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        duplicate_source_mesh = service.working_mesh(duplicate_source_view.session_id)
        self.assertTrue(duplicate_source.ok)
        self.assertTrue(duplicate_source.topology_changed)
        self.assertEqual((1,), duplicate_source.affected_submesh_indices)
        self.assertEqual(2, len(duplicate_source_mesh.submeshes))
        self.assertEqual(2, duplicate_source_mesh.submeshes[1].face_count)

        mirror_empty_view = service.open_edit_session(_quad_mesh(), session_id="mirror-empty-target", mode="edit")
        mirror_empty = service.apply_command(mirror_empty_view.session_id, MeshEditCommand("mirror", params={"axis": "x"}))
        self.assertTrue(mirror_empty.ok)
        self.assertFalse(mirror_empty.topology_changed)
        self.assertEqual((), mirror_empty.affected_submesh_indices)
        self.assertEqual(1, service.session_view(mirror_empty_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(mirror_empty_view.session_id).revision)

        mirror_invalid_face_view = service.open_edit_session(_quad_mesh(), session_id="mirror-invalid-face-target", mode="edit")
        mirror_invalid_face = service.apply_command(
            mirror_invalid_face_view.session_id,
            MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)}), params={"axis": "x"}),
        )
        self.assertTrue(mirror_invalid_face.ok)
        self.assertFalse(mirror_invalid_face.topology_changed)
        self.assertEqual((), mirror_invalid_face.affected_submesh_indices)
        self.assertEqual(1, service.session_view(mirror_invalid_face_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(mirror_invalid_face_view.session_id).revision)

        mirror_source_view = service.open_edit_session(_quad_mesh(), session_id="mirror-source-target", mode="edit")
        mirror_source = service.apply_command(
            mirror_source_view.session_id,
            MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"axis": "x"}),
        )
        mirror_source_mesh = service.working_mesh(mirror_source_view.session_id)
        self.assertTrue(mirror_source.ok)
        self.assertTrue(mirror_source.topology_changed)
        self.assertEqual((1,), mirror_source.affected_submesh_indices)
        self.assertEqual(2, len(mirror_source_mesh.submeshes))
        self.assertEqual((0.0, 0.0, 0.0), mirror_source_mesh.submeshes[1].vertices[0])
        self.assertEqual((-1.0, 0.0, 0.0), mirror_source_mesh.submeshes[1].vertices[1])

        mirror_in_place_empty_view = service.open_edit_session(_quad_mesh(), session_id="mirror-in-place-empty-target", mode="edit")
        mirror_in_place_empty = service.apply_command(
            mirror_in_place_empty_view.session_id,
            MeshEditCommand("mirror", params={"axis": "x", "in_place": True}),
        )
        mirror_in_place_empty_mesh = service.working_mesh(mirror_in_place_empty_view.session_id)
        self.assertTrue(mirror_in_place_empty.ok)
        self.assertEqual((), mirror_in_place_empty.affected_submesh_indices)
        self.assertEqual((), mirror_in_place_empty.changed_vertices_by_submesh)
        self.assertEqual((1.0, 0.0, 0.0), mirror_in_place_empty_mesh.submeshes[0].vertices[1])

    def test_duplicate_derives_face_copy_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-edge-face", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        copied = mesh.submeshes[1]
        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual((1,), duplicated.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, copied.vertex_count)
        self.assertEqual(1, copied.face_count)
        self.assertEqual([(0, 1, 2)], copied.faces)

    def test_mirror_derives_face_copy_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mirror-edge-face", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"material": "routed", "texture": "routed.dds", "material_profile": "runtime_xml", "route_status": "ready"},
            ),
        )

        mirrored = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "mirror",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                params={"axis": "x"},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        copied = mesh.submeshes[1]
        self.assertTrue(mirrored.ok)
        self.assertTrue(mirrored.topology_changed)
        self.assertEqual((1,), mirrored.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, copied.vertex_count)
        self.assertEqual(1, copied.face_count)
        self.assertEqual([(0, 2, 1)], copied.faces)
        self.assertEqual([(0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], copied.vertices)
        self.assertEqual("routed", copied.material)
        self.assertEqual("runtime_xml", getattr(copied, "cdmw_material_authority_profile"))
        self.assertEqual("ready", getattr(copied, "cdmw_material_route_status"))

    def test_duplicate_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-stale-edge", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(duplicated.ok)
        self.assertFalse(duplicated.topology_changed)
        self.assertEqual((), duplicated.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_split_detaches_selected_faces_in_place(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="split-edge-face", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        mesh = service.working_mesh(view.session_id)
        submesh = mesh.submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(4, 6)),), result.changed_vertices_by_submesh)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(6, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 4, 5), (1, 3, 2)], submesh.faces)
        self.assertEqual((1.0, 0.0, 0.0), submesh.vertices[4])
        self.assertEqual((0.0, 1.0, 0.0), submesh.vertices[5])

    def test_separate_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="separate-edge-face", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("separate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        mesh = service.working_mesh(view.session_id)
        source = mesh.submeshes[0]
        moved = mesh.submeshes[1]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0, 1), result.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, source.vertex_count)
        self.assertEqual(1, source.face_count)
        self.assertEqual([(0, 2, 1)], source.faces)
        self.assertEqual(3, moved.vertex_count)
        self.assertEqual(1, moved.face_count)
        self.assertEqual([(0, 1, 2)], moved.faces)

    def test_split_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="split-stale-edge", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertFalse(result.topology_changed)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_subdivide_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="subdivide-edge-face", mode="edit")

        subdivided = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(subdivided.ok)
        self.assertTrue(subdivided.topology_changed)
        self.assertEqual((0,), subdivided.affected_submesh_indices)
        self.assertEqual(7, submesh.vertex_count)
        self.assertEqual(5, submesh.face_count)
        self.assertEqual((1, 3, 2), submesh.faces[-1])
        self.assertEqual({0, 1, 2, 4, 5, 6}, _changed_vertices_as_set(subdivided))

    def test_subdivide_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="subdivide-stale-edge", mode="edit")

        subdivided = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(subdivided.ok)
        self.assertFalse(subdivided.topology_changed)
        self.assertEqual((), subdivided.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual(2, mesh.submeshes[0].face_count)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_delete_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="delete-edge-face", mode="edit")

        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand("delete", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(3, submesh.vertex_count)
        self.assertEqual(1, submesh.face_count)
        self.assertEqual([(0, 2, 1)], submesh.faces)

    def test_dissolve_derives_exact_face_targets_from_edge_selection_without_orphan_compaction(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dissolve-edge-face", mode="edit")

        dissolved = service.apply_command(
            view.session_id,
            MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(dissolved.ok)
        self.assertTrue(dissolved.topology_changed)
        self.assertEqual((0,), dissolved.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(1, submesh.face_count)
        self.assertEqual([(1, 3, 2)], submesh.faces)

    def test_dissolve_internal_edge_retriangulates_quad_region(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dissolve-internal-edge", mode="edit")

        dissolved = service.apply_command(
            view.session_id,
            MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(dissolved.ok)
        self.assertTrue(dissolved.topology_changed)
        self.assertEqual((0,), dissolved.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], submesh.faces)

    def test_dissolve_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-dissolve", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_dissolve", side_effect=AssertionError("legacy dissolve helper")),
            patch("cdmw.modding.mesh_edit_ops._dissolve_internal_edges", side_effect=AssertionError("python dissolve loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("dissolve", selection=selection))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], working.submeshes[0].faces)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], service.working_mesh(view.session_id).submeshes[0].faces)
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)

    def test_material_actions_noop_without_assign_params_or_copy_target_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-noop", mode="edit")

        assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        untargeted_assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", params={"material": "untargeted", "texture": "untargeted.dds"}),
        )
        copy = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", params={"source_submesh_index": 0}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(assign.ok)
        self.assertEqual((), assign.affected_submesh_indices)
        self.assertTrue(untargeted_assign.ok)
        self.assertEqual((), untargeted_assign.affected_submesh_indices)
        self.assertTrue(copy.ok)
        self.assertEqual((), copy.affected_submesh_indices)
        self.assertEqual(0, state.revision)
        self.assertEqual(0, state.undo_count)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("a.dds", mesh.submeshes[0].texture)
        self.assertEqual("mat_b", mesh.submeshes[1].material)
        self.assertEqual("b.dds", mesh.submeshes[1].texture)

    def test_material_copy_noops_on_malformed_source_index(self) -> None:
        malformed_values = ("bad", float("inf"), 0.5, True)
        for value in malformed_values:
            with self.subTest(value=value):
                service = MeshService()
                view = service.open_edit_session(_quad_mesh(two_parts=True), session_id=f"material-copy-bad-source-{value}", mode="edit")
                before = [(submesh.material, submesh.texture) for submesh in service.working_mesh(view.session_id).submeshes]

                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "material_copy",
                        selection=MeshEditSelection.from_maps(source_indices=(1,)),
                        params={"source_submesh_index": value},
                    ),
                )

                self.assertTrue(result.ok)
                self.assertEqual((), result.affected_submesh_indices)
                self.assertFalse(result.topology_changed)
                self.assertEqual(0, service.session_view(view.session_id).revision)
                self.assertEqual(before, [(submesh.material, submesh.texture) for submesh in service.working_mesh(view.session_id).submeshes])

    def test_identity_material_assign_and_copy_do_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-identity", mode="edit")

        assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"material": "mat_a", "texture": "a.dds"}),
        )
        copy = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )
        copy_again = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(assign.ok)
        self.assertEqual((), assign.affected_submesh_indices)
        self.assertTrue(copy.ok)
        self.assertEqual((1,), copy.affected_submesh_indices)
        self.assertTrue(copy_again.ok)
        self.assertEqual((), copy_again.affected_submesh_indices)
        self.assertEqual(1, state.revision)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("mat_a", mesh.submeshes[1].material)

    def test_uv_transform_can_expand_to_selected_uv_island(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-island", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"uv_island": True, "offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[0])
        self.assertEqual((0.75, 0.0), mesh.submeshes[0].uvs[1])
        self.assertEqual((0.25, 0.5), mesh.submeshes[0].uvs[2])
        self.assertEqual((2.0, 0.0), mesh.submeshes[0].uvs[3])

    def test_uv_transform_can_normalize_selected_uv_bounds(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-normalize", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (3, 4, 5)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"normalize": True}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(3, 6)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0), uvs[3])
        self.assertEqual((1.0, 0.0), uvs[4])
        self.assertEqual((0.0, 1.0), uvs[5])
        self.assertEqual((0.0, 0.0), uvs[0])

    def test_uv_transform_can_align_selected_uv_axis(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-align", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 3)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"align_v": "min"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(3, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual((1.0, 0.0), uvs[1])
        self.assertEqual((1.0, 0.0), uvs[3])
        self.assertEqual((0.0, 1.0), uvs[2])

    def test_uv_transform_can_project_selected_vertices_planar(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 4
        view = service.open_edit_session(mesh, session_id="uv-planar", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"projection": "planar", "plane": "xy"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(uvs))

    def test_uv_projection_initializes_missing_uvs_for_auto_uv_fallback(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.has_uvs = False
        mesh.submeshes[0].uvs = []
        view = service.open_edit_session(mesh, session_id="uv-missing-planar", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"projection": "planar", "plane": "xy"},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 4)),), result.changed_vertices_by_submesh)
        self.assertTrue(mesh.has_uvs)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))

    def test_uv_transform_can_project_selected_vertices_box(self) -> None:
        service = MeshService()
        submesh = SubMesh(
            name="box_projection",
            material="mat",
            texture="uv.dds",
            vertices=[(5.0, 0.0, 0.0), (5.0, 1.0, 0.0), (5.0, 0.0, 2.0)],
            uvs=[(0.0, 0.0)] * 3,
            normals=[(1.0, 0.0, 0.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        view = service.open_edit_session(
            ParsedMesh(path="box.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True),
            session_id="uv-box",
            mode="edit",
        )

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"projection": "box"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), tuple(uvs))

    def test_uv_transform_can_project_selected_vertices_cylindrical(self) -> None:
        service = MeshService()
        submesh = SubMesh(
            name="cylinder_projection",
            material="mat",
            texture="uv.dds",
            vertices=[(1.0, 0.0, 0.0), (0.0, 1.0, 1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 2), (0, 3, 2)],
            vertex_count=4,
            face_count=2,
        )
        view = service.open_edit_session(
            ParsedMesh(path="cyl.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=2, has_uvs=True),
            session_id="uv-cyl",
            mode="edit",
        )

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"projection": "cylindrical"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 4)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(0.5, uvs[0][0], places=6)
        self.assertAlmostEqual(0.0, uvs[0][1], places=6)
        self.assertAlmostEqual(0.75, uvs[1][0], places=6)
        self.assertAlmostEqual(1.0, uvs[1][1], places=6)
        self.assertAlmostEqual(1.0, uvs[2][0], places=6)
        self.assertAlmostEqual(0.0, uvs[2][1], places=6)
        self.assertAlmostEqual(0.25, uvs[3][0], places=6)
        self.assertAlmostEqual(1.0, uvs[3][1], places=6)

    def test_uv_transform_can_pack_selected_uv_islands(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-pack", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"pack": True, "padding": 0.0}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(2, 6)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (0.5, 0.0), (0.0, 1.0), (0.5, 0.0), (1.0, 0.0), (0.5, 1.0)), tuple(uvs))

    def test_uv_transform_can_snap_selected_uvs_to_grid_and_pixels(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].uvs[0] = (0.12, 0.39)
        mesh.submeshes[0].uvs[1] = (0.13, 0.62)
        view = service.open_edit_session(mesh, session_id="uv-snap", mode="edit")

        grid = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), params={"snap_grid": 0.25}),
        )
        pixels = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                params={"pixel_snap": True, "texture_size": (4.0, 4.0)},
            ),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(grid.ok)
        self.assertTrue(pixels.ok)
        self.assertEqual((0.0, 0.5), uvs[0])
        self.assertEqual((0.25, 0.5), uvs[1])

    def test_select_uv_region_updates_session_selection_without_editing_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-region-select", mode="edit")
        selected = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 2)})

        with (
            patch("cdmw.services.mesh_service.select_native_mesh_uv_vertices", return_value={0: {0, 2}}),
            patch("cdmw.services.mesh_service._apply_native_editor_session_selection_operation", return_value=(selected, (), (), {})),
        ):
            result = service.select_uv_region(view.session_id, (0.0, 0.0), (0.1, 1.0))

        selection = service.session_view(view.session_id).selection
        summary = service.uv_summary(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual("select", result.action)
        self.assertEqual(0, result.revision)
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        self.assertEqual(1, summary.selected_island_count)

    def test_select_uv_lasso_updates_session_selection_without_editing_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-lasso-select", mode="edit")
        selected = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 2)})

        with (
            patch("cdmw.services.mesh_service.select_native_mesh_uv_vertices", return_value={0: {0, 2}}),
            patch("cdmw.services.mesh_service._apply_native_editor_session_selection_operation", return_value=(selected, (), (), {})),
        ):
            result = service.select_uv_lasso(
                view.session_id,
                ((-0.1, -0.1), (0.2, -0.1), (0.2, 1.1), (-0.1, 1.1)),
            )

        selection = service.session_view(view.session_id).selection
        self.assertTrue(result.ok)
        self.assertEqual("select", result.action)
        self.assertEqual(0, result.revision)
        self.assertEqual({0: {0, 2}}, selection.vertex_map())

    def test_select_uv_region_uses_native_hit_test_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-uv-region-select", mode="edit")
        selected = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 3)})

        with (
            patch("cdmw.services.mesh_service.select_native_mesh_uv_vertices", return_value={0: {1, 3}}) as native_select,
            patch(
                "cdmw.services.mesh_service._apply_native_editor_session_selection_operation",
                return_value=(selected, (), (), {}),
            ) as native_resident_select,
        ):
            result = service.select_uv_region(view.session_id, (0.9, 0.0), (1.1, 1.0))

        selection = service.session_view(view.session_id).selection
        self.assertTrue(result.ok)
        self.assertEqual({0: {1, 3}}, selection.vertex_map())
        native_select.assert_called_once()
        self.assertEqual("region", native_select.call_args.kwargs["mode"])
        self.assertEqual((0.9, 0.0), native_select.call_args.kwargs["uv_min"])
        self.assertEqual((1.1, 1.0), native_select.call_args.kwargs["uv_max"])
        native_resident_select.assert_called_once()
        self.assertEqual({0: {1, 3}}, native_resident_select.call_args.args[1].vertex_map())

    def test_select_uv_lasso_uses_native_hit_test_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-uv-lasso-select", mode="edit")
        polygon = ((-0.1, -0.1), (0.2, -0.1), (0.2, 1.1), (-0.1, 1.1))
        selected = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 2)})

        with (
            patch("cdmw.services.mesh_service.select_native_mesh_uv_vertices", return_value={0: {0, 2}}) as native_select,
            patch(
                "cdmw.services.mesh_service._apply_native_editor_session_selection_operation",
                return_value=(selected, (), (), {}),
            ) as native_resident_select,
        ):
            result = service.select_uv_lasso(view.session_id, polygon)

        selection = service.session_view(view.session_id).selection
        self.assertTrue(result.ok)
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        native_select.assert_called_once()
        self.assertEqual("lasso", native_select.call_args.kwargs["mode"])
        self.assertEqual(polygon, native_select.call_args.kwargs["points"])
        native_resident_select.assert_called_once()
        self.assertEqual({0: {0, 2}}, native_resident_select.call_args.args[1].vertex_map())

    def test_uv_selection_blocks_python_fallback_when_native_unavailable(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        cases = (
            ("uv.region", "select_uv_region", ((0.0, 0.0), (1.0, 1.0))),
            (
                "uv.lasso",
                "select_uv_lasso",
                (((-0.1, -0.1), (1.1, -0.1), (1.1, 1.1), (-0.1, 1.1)),),
            ),
        )
        clear_native_mesh_core_fallback_counts()
        try:
            for operation, method_name, args in cases:
                with self.subTest(operation=operation):
                    service = MeshService()
                    view = service.open_edit_session(_quad_mesh(), session_id=f"strict-{operation}", mode="edit")
                    with (
                        patch("cdmw.services.mesh_service.prune_native_mesh_selection", return_value={}),
                        patch("cdmw.services.mesh_service.select_native_mesh_uv_vertices", return_value=None),
                    ):
                        result = getattr(service, method_name)(view.session_id, *args)

                    self.assertFalse(result.ok)
                    self.assertEqual("error", result.status)
                    self.assertEqual("select", result.action)
                    self.assertEqual({}, service.session_view(view.session_id).selection.vertex_map())
                    self.assertEqual(1, len(result.diagnostics))
                    self.assertIn("Python fallback was blocked", result.diagnostics[0])
                    self.assertIn("4 vertices", result.diagnostics[0])
            fallback_counts = native_mesh_core_fallback_counts()
            self.assertEqual(1, fallback_counts["uv.region.blocked"])
            self.assertEqual(1, fallback_counts["uv.lasso.blocked"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_native_mesh_session_ids_are_per_mesh_tokens(self) -> None:
        from cdmw.modding import mesh_native_core

        first = _quad_mesh()
        second = _quad_mesh()

        first_session = mesh_native_core._native_mesh_session_id(first, 0)
        self.assertEqual(first_session, mesh_native_core._native_mesh_session_id(first, 0))
        self.assertNotEqual(first_session, mesh_native_core._native_mesh_session_id(second, 0))
        self.assertTrue(first_session.startswith("py-mesh-"))

    def test_native_mesh_session_store_returns_none_if_service_stops_after_store(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        binary = Path("native.exe")
        mesh_native_core._clear_native_mesh_core_session_cache()
        with (
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_known_for_binary", return_value=True),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", side_effect=(True, False)),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", return_value={"status": "ok"}),
        ):
            self.assertIsNone(mesh_native_core._ensure_native_mesh_session_submesh(binary, mesh, 0, timeout_seconds=1.0))
        self.assertFalse(mesh_native_core._native_mesh_core_session_cache)

    def test_native_mesh_core_uv_selection_uses_binary_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-selection-json", command)
            self.assertEqual("uv_selection", payload["operation"])  # type: ignore[index]
            self.assertEqual("region", payload["mode"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("uvs_binary", submesh_payload)
            self.assertIn("selected_vertices_output_path", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            self.assertEqual(4, submesh_payload["uvs_binary"]["count"])
            self.assertTrue(Path(submesh_payload["uvs_binary"]["path"]).is_file())
            self.assertEqual(5.0, timeout_seconds)
            selected_path = Path(str(submesh_payload["selected_vertices_output_path"]))
            selected_path.write_bytes(array("i", (0, 2)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_selection",
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertices_binary": {
                            "path": str(selected_path),
                            "count": 2,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            selected = mesh_native_core.select_native_mesh_uv_vertices(
                mesh,
                mode="region",
                uv_min=(0.0, 0.0),
                uv_max=(0.1, 1.0),
            )

        self.assertEqual({0: {0, 2}}, selected)

    def test_native_mesh_core_uv_selection_uses_resident_session_without_uv_sidecar(self) -> None:
        from cdmw.modding import mesh_native_core

        class ExplodingUvs:
            def __bool__(self) -> bool:
                raise AssertionError("uv fallback should not inspect Python uvs")

            def __len__(self) -> int:
                raise AssertionError("uv fallback should not inspect Python uvs")

            def __iter__(self):
                raise AssertionError("uv fallback should not inspect Python uvs")

        mesh = _quad_mesh()
        mesh.submeshes[0].uvs = ExplodingUvs()  # type: ignore[assignment]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-selection-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual("session-uv-0", submesh_payload["session_id"])
            self.assertNotIn("uvs_binary", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_selection",
                "submeshes": [
                    {
                        "index": 0,
                        "selected_vertex_start": 1,
                        "selected_vertex_count": 2,
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-uv-0"),
            patch("cdmw.modding.mesh_native_core._write_vec2_binary_payload", side_effect=AssertionError("uv sidecar write")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            selected = mesh_native_core.select_native_mesh_uv_vertices(
                mesh,
                mode="region",
                uv_min=(0.0, 0.0),
                uv_max=(1.0, 1.0),
            )

        self.assertEqual({0: {1, 2}}, selected)

    def test_native_mesh_core_uv_selection_reports_contiguous_selection_as_range(self) -> None:
        from cdmw.modding import mesh_native_core

        binary = mesh_native_core.find_native_mesh_core_binary()
        if binary is None:
            self.skipTest("native mesh core binary not built")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uvs_path = root / "uvs.bin"
            selected_path = root / "selected.bin"
            data = array("d")
            for uv in ((0.0, 0.0), (0.25, 0.0), (0.5, 0.0), (0.75, 0.0)):
                data.extend(uv)
            uvs_path.write_bytes(data.tobytes())

            report = mesh_native_core._run_native_mesh_core_job(
                binary,
                "uv-selection-json",
                {
                    "version": 1,
                    "backend": "cdmw_mesh_core_0.1",
                    "operation": "uv_selection",
                    "mode": "region",
                    "uv_min": [0.0, -0.1],
                    "uv_max": [1.0, 0.1],
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": 4,
                            "uvs_binary": {
                                "path": str(uvs_path),
                                "count": 4,
                                "components": 2,
                                "type": "f64",
                            },
                            "selected_vertices_output_path": str(selected_path),
                        }
                    ],
                },
                timeout_seconds=5.0,
            )

            self.assertIsNotNone(report)
            item = report["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, item["selected_vertex_start"])  # type: ignore[index]
            self.assertEqual(4, item["selected_vertex_count"])  # type: ignore[index]
            self.assertNotIn("selected_vertices_binary", item)
            self.assertFalse(selected_path.exists())

    def test_uv_transform_uses_native_mesh_core_when_available(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-uv-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)})
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with patch(
            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
            side_effect=AssertionError("resident native UV session not used"),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("uv_transform", selection=selection, params={"offset": (0.25, 0.0)}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((1.25, 0.0), service.working_mesh(view.session_id).submeshes[0].uvs[1])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_uv_transform_source_selection_uses_native_range_before_python_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id="native-uv-source-range", mode="edit")
        vertex_count = service.working_mesh(view.session_id).submeshes[0].vertex_count
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with (
            patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("resident native UV session not used"),
            ),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python UV source vertex expansion reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "uv_transform",
                    selection=MeshEditSelection.from_maps(source_indices=(0,)),
                    params={"offset": (0.25, 0.0)},
                ),
            )

        changed = dict(result.changed_vertices_by_submesh)[0]
        self.assertTrue(result.ok)
        self.assertIsInstance(changed, range)
        self.assertEqual(range(vertex_count), changed)
        self.assertEqual((0.25, 0.0), service.working_mesh(view.session_id).submeshes[0].uvs[-1])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_uv_transform_edge_selection_forwards_native_domains_before_python_expansion(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-uv-edge-domain", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()

        with (
            patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("resident native UV session not used"),
            ),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python UV edge vertex expansion reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "uv_transform",
                    selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                    params={"offset": (0.25, 0.0)},
                ),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((1.25, 0.0), service.working_mesh(view.session_id).submeshes[0].uvs[1])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_native_mesh_core_uv_transform_uses_binary_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-transform-json", command)
            self.assertEqual("uv_transform", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("uvs_binary", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertEqual(4, submesh_payload["uvs_binary"]["count"])
            self.assertTrue(Path(submesh_payload["uvs_binary"]["path"]).is_file())
            self.assertEqual(5.0, timeout_seconds)
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            uv_data = array("d")
            for uv in ((0.0, 0.0), (1.25, 0.0), (0.0, 1.0), (1.0, 1.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            changed_vertices_output_path.write_bytes(array("i", (1,)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 4,
                            "components": 2,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_uv_transform(
                mesh,
                {0: {1}},
                offset=(0.25, 0.0),
                scale=(1.0, 1.0),
                rotate_degrees=0.0,
            )

        self.assertEqual({0: [1]}, changed)
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])

    def test_native_mesh_core_uv_transform_keeps_range_selection_compact(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(4, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            uv_data = array("d")
            for uv in ((0.25, 0.0), (1.25, 0.0), (0.25, 1.0), (1.25, 1.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertex_start": 0,
                        "changed_vertex_count": 4,
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 4,
                            "components": 2,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch("cdmw.modding.mesh_native_core._write_int_binary_payload", side_effect=AssertionError("range selection should stay compact")),
        ):
            changed = mesh_native_core.apply_native_mesh_uv_transform(
                mesh,
                {0: range(4)},
                offset=(0.25, 0.0),
                scale=(1.0, 1.0),
                rotate_degrees=0.0,
            )

        self.assertIsInstance(changed[0], range)  # type: ignore[index]
        self.assertEqual(range(4), changed[0])  # type: ignore[index]
        self.assertEqual((1.25, 1.0), mesh.submeshes[0].uvs[3])

    def test_native_mesh_core_uv_transform_expands_edge_domain_in_cpp(self) -> None:
        from cdmw.modding import mesh_native_core

        if mesh_native_core.find_native_mesh_core_binary() is None:
            self.skipTest("native mesh core binary not built")

        mesh = _quad_mesh()
        changed = mesh_native_core.apply_native_mesh_uv_transform(
            mesh,
            {},
            selected_edges_by_submesh={0: {(0, 1)}},
            offset=(0.25, 0.0),
            scale=(1.0, 1.0),
            rotate_degrees=0.0,
        )

        self.assertEqual({0, 1}, set(changed[0]))  # type: ignore[index]
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[0])
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])
        self.assertEqual((0.0, 1.0), mesh.submeshes[0].uvs[2])

    def test_native_uv_transform_report_accepts_compact_changed_range(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        uvs_path = Path(tempfile.gettempdir()) / f"cdmw-uvs-{uuid4().hex}.bin"
        self.addCleanup(lambda: uvs_path.unlink(missing_ok=True))
        uv_values = array("d")
        for uv in ((0.0, 0.0), (1.25, 0.0), (0.25, 1.0), (1.0, 1.0)):
            uv_values.extend(uv)
        uvs_path.write_bytes(uv_values.tobytes())
        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "uv_transform",
            "submeshes": [
                {
                    "index": 0,
                    "changed_vertex_start": 1,
                    "changed_vertex_count": 2,
                    "uvs_binary": {"path": str(uvs_path), "count": 4, "components": 2, "type": "f64"},
                }
            ],
        }

        changed = mesh_native_core._apply_uv_transform_report(mesh, report)

        self.assertIsInstance(changed[0], range)  # type: ignore[index]
        self.assertEqual(range(1, 3), changed[0])  # type: ignore[index]
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])
        self.assertNotIn("changed_vertices_binary", report["submeshes"][0])

    def test_native_mesh_core_uv_transform_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        store_payloads: list[object] = []

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("uvs_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("uv-transform-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            self.assertEqual(1, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertNotIn("vertex_count", submesh_payload)
            self.assertNotIn("uvs_binary", submesh_payload)
            self.assertNotIn("uvs", submesh_payload)
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            uv_data = array("d")
            for uv in ((0.0, 0.0), (1.25, 0.0), (0.0, 1.0), (1.0, 1.0)):
                uv_data.extend(uv)
            uvs_output_path.write_bytes(uv_data.tobytes())
            changed_vertices_output_path.write_bytes(array("i", (1,)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "uv_transform",
                "submeshes": [
                    {
                        "index": 0,
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 4,
                            "components": 2,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            changed = mesh_native_core.apply_native_mesh_uv_transform(
                mesh,
                {0: {1}},
                offset=(0.25, 0.0),
                scale=(1.0, 1.0),
                rotate_degrees=0.0,
            )

        self.assertEqual(1, len(store_payloads))
        self.assertEqual({0: [1]}, changed)
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])

    def test_native_mesh_core_auto_uv_report_uses_xatlas_command(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("auto-uv-json", command)
            self.assertEqual("auto_uv", payload["operation"])  # type: ignore[index]
            self.assertEqual(256, payload["auto_uv"]["resolution"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("vertices_output_path", submesh_payload)
            self.assertIn("vertex_remap_output_path", submesh_payload)
            self.assertIn("faces_output_path", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertIn("normals_output_path", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertEqual(4, submesh_payload["vertices_binary"]["count"])
            self.assertEqual(2, submesh_payload["faces_binary"]["count"])
            self.assertTrue(Path(submesh_payload["vertices_binary"]["path"]).is_file())
            self.assertTrue(Path(submesh_payload["faces_binary"]["path"]).is_file())
            self.assertEqual(15.0, timeout_seconds)
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            vertex_remap_path = Path(str(submesh_payload["vertex_remap_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            vertex_values = array("d")
            for vertex in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)):
                vertex_values.extend(vertex)
            vertices_output_path.write_bytes(vertex_values.tobytes())
            vertex_remap_path.write_bytes(array("i", (0, 1, 2, 2, 3)).tobytes())
            faces_output_path.write_bytes(array("i", (0, 1, 2, 3, 1, 4)).tobytes())
            uv_values = array("d")
            for uv in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.2, 0.2), (1.0, 1.0)):
                uv_values.extend(uv)
            uvs_output_path.write_bytes(uv_values.tobytes())
            changed_vertices_output_path.write_bytes(array("i", (0, 1, 2, 3, 4)).tobytes())
            normal_values = array("d")
            for normal in ((0.0, 0.0, 1.0),) * 5:
                normal_values.extend(normal)
            normals_output_path.write_bytes(normal_values.tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "auto_uv",
                "unwrap_backend": "xatlas",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "status": "ok",
                        "unwrap_backend": "xatlas",
                        "input_vertex_count": 4,
                        "output_vertex_count": 5,
                        "input_face_count": 2,
                        "output_face_count": 2,
                        "chart_count": 2,
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "vertex_remap_binary": {
                            "path": str(vertex_remap_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 5,
                            "components": 2,
                            "type": "f64",
                        },
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=False),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            report = mesh_native_core.native_mesh_auto_uv_report(mesh, {0}, resolution=256)

        self.assertEqual("xatlas", report["unwrap_backend"])
        self.assertTrue(report["topology_changed"])
        self.assertEqual(5, report["submeshes"][0]["output_vertex_count"])
        self.assertIn("vertices_binary", report["submeshes"][0])
        self.assertIn("vertex_remap_binary", report["submeshes"][0])
        self.assertIn("faces_binary", report["submeshes"][0])
        self.assertIn("uvs_binary", report["submeshes"][0])
        self.assertIn("normals_binary", report["submeshes"][0])
        self.assertNotIn("vertex_remap", report["submeshes"][0])
        self.assertNotIn("faces", report["submeshes"][0])
        self.assertNotIn("uvs", report["submeshes"][0])

    def test_native_mesh_core_auto_uv_report_uses_resident_service_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.tangents = [(1.0, 0.0, 0.0)] * 4
        submesh.tangent_signs = [1.0] * 4
        submesh.bone_indices = [(0,), (1,), (2,), (3,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        submesh.source_vertex_map = [10, 11, 12, 13]
        submesh.source_vertex_offsets = [100, 110, 120, 130]
        store_payloads: list[object] = []
        native_report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "auto_uv",
            "unwrap_backend": "xatlas",
            "topology_changed": False,
            "submeshes": [{"index": 0, "status": "ok", "input_vertex_count": 4, "output_vertex_count": 4}],
        }

        def service_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("mesh-session-json", command)
            store_payloads.append(payload)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertices_binary", submesh_payload)
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("tangents_binary", submesh_payload)
            self.assertIn("bone_counts_binary", submesh_payload)
            self.assertEqual(10, submesh_payload["source_vertex_map_start"])
            self.assertEqual(4, submesh_payload["source_vertex_map_count"])
            self.assertNotIn("source_vertex_map_binary", submesh_payload)
            self.assertEqual(100, submesh_payload["source_vertex_offsets_start"])
            self.assertEqual(4, submesh_payload["source_vertex_offsets_count"])
            self.assertEqual(10, submesh_payload["source_vertex_offsets_stride"])
            self.assertNotIn("source_vertex_offsets_binary", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "mesh_session",
                "session_id": payload["session_id"],  # type: ignore[index]
                "submesh_count": 1,
            }

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("auto-uv-json", command)
            self.assertEqual("auto_uv", payload["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("session_id", submesh_payload)
            for key in (
                "vertices_binary",
                "faces_binary",
                "normals_binary",
                "tangents_binary",
                "tangent_signs_binary",
                "bone_counts_binary",
                "source_vertex_map_binary",
                "source_vertex_offsets_binary",
            ):
                self.assertNotIn(key, submesh_payload)
            for key in (
                "vertices_output_path",
                "faces_output_path",
                "uvs_output_path",
                "changed_vertices_output_path",
                "normals_output_path",
                "tangents_output_path",
                "tangent_signs_output_path",
                "bone_counts_output_path",
                "source_vertex_map_output_path",
                "source_vertex_offsets_output_path",
            ):
                self.assertIn(key, submesh_payload)
            return native_report

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_running", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
            patch(
                "cdmw.modding.mesh_native_core._face_json",
                side_effect=AssertionError("resident auto-uv path must not rebuild face sidecars"),
            ),
        ):
            mesh_native_core._clear_native_mesh_core_session_cache()
            report = mesh_native_core.native_mesh_auto_uv_report(mesh, {0}, resolution=256)

        self.assertEqual(1, len(store_payloads))
        self.assertEqual(native_report, report)

    def test_native_mesh_core_auto_uv_apply_remaps_vertex_aligned_attributes(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        submesh.normals = [(0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)]
        submesh.tangents = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)]
        submesh.tangent_signs = [1.0, -1.0, 1.0, -1.0]
        submesh.bone_indices = [(0,), (1,), (2,), (3,)]
        submesh.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        submesh.source_vertex_map = [10, 11, 12, 13]
        submesh.source_vertex_offsets = [100, 110, 120, 130]

        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("auto-uv-json", command)
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertIn("vertex_remap_output_path", submesh_payload)
            self.assertIn("faces_output_path", submesh_payload)
            self.assertIn("uvs_output_path", submesh_payload)
            self.assertIn("changed_vertices_output_path", submesh_payload)
            self.assertIn("vertices_output_path", submesh_payload)
            self.assertIn("normals_output_path", submesh_payload)
            self.assertIn("tangents_output_path", submesh_payload)
            self.assertIn("tangent_signs_output_path", submesh_payload)
            self.assertIn("bone_counts_output_path", submesh_payload)
            self.assertIn("source_vertex_map_output_path", submesh_payload)
            vertex_remap_path = Path(str(submesh_payload["vertex_remap_output_path"]))
            faces_output_path = Path(str(submesh_payload["faces_output_path"]))
            uvs_output_path = Path(str(submesh_payload["uvs_output_path"]))
            changed_vertices_output_path = Path(str(submesh_payload["changed_vertices_output_path"]))
            vertices_output_path = Path(str(submesh_payload["vertices_output_path"]))
            normals_output_path = Path(str(submesh_payload["normals_output_path"]))
            tangents_output_path = Path(str(submesh_payload["tangents_output_path"]))
            tangent_signs_output_path = Path(str(submesh_payload["tangent_signs_output_path"]))
            bone_counts_output_path = Path(str(submesh_payload["bone_counts_output_path"]))
            bone_indices_output_path = Path(str(submesh_payload["bone_indices_output_path"]))
            bone_weights_output_path = Path(str(submesh_payload["bone_weights_output_path"]))
            source_vertex_map_output_path = Path(str(submesh_payload["source_vertex_map_output_path"]))
            source_vertex_offsets_output_path = Path(str(submesh_payload["source_vertex_offsets_output_path"]))
            vertex_remap_path.write_bytes(array("i", (0, 1, 2, 2, 3)).tobytes())
            faces_output_path.write_bytes(array("i", (0, 1, 2, 3, 1, 4)).tobytes())
            vertex_values = array("d")
            for vertex in (submesh.vertices[0], submesh.vertices[1], submesh.vertices[2], submesh.vertices[2], submesh.vertices[3]):
                vertex_values.extend(vertex)
            vertices_output_path.write_bytes(vertex_values.tobytes())
            uv_values = array("d")
            for uv in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.25, 0.25), (1.0, 1.0)):
                uv_values.extend(uv)
            uvs_output_path.write_bytes(uv_values.tobytes())
            changed_vertices_output_path.write_bytes(array("i", (0, 1, 2, 3, 4)).tobytes())
            normal_values = array("d")
            for normal in (submesh.normals[0], submesh.normals[1], submesh.normals[2], submesh.normals[2], submesh.normals[3]):
                normal_values.extend(normal)
            normals_output_path.write_bytes(normal_values.tobytes())
            tangent_values = array("d")
            for tangent in (submesh.tangents[0], submesh.tangents[1], submesh.tangents[2], submesh.tangents[2], submesh.tangents[3]):
                tangent_values.extend(tangent)
            tangents_output_path.write_bytes(tangent_values.tobytes())
            tangent_signs_output_path.write_bytes(array("d", (1.0, -1.0, 1.0, 1.0, -1.0)).tobytes())
            bone_counts_output_path.write_bytes(array("i", (1, 1, 1, 1, 1)).tobytes())
            bone_indices_output_path.write_bytes(array("i", (0, 1, 2, 2, 3)).tobytes())
            bone_weights_output_path.write_bytes(array("d", (1.0, 1.0, 1.0, 1.0, 1.0)).tobytes())
            source_vertex_map_output_path.write_bytes(array("i", (10, 11, 12, 12, 13)).tobytes())
            source_vertex_offsets_output_path.write_bytes(array("i", (100, 110, 120, 120, 130)).tobytes())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "auto_uv",
                "unwrap_backend": "xatlas",
                "topology_changed": True,
                "submeshes": [
                    {
                        "index": 0,
                        "status": "ok",
                        "unwrap_backend": "xatlas",
                        "topology_changed": True,
                        "input_vertex_count": 4,
                        "output_vertex_count": 5,
                        "input_face_count": 2,
                        "output_face_count": 2,
                        "chart_count": 2,
                        "vertices_binary": {
                            "path": str(vertices_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "vertex_remap_binary": {
                            "path": str(vertex_remap_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "faces_binary": {
                            "path": str(faces_output_path),
                            "count": 2,
                            "components": 3,
                            "type": "i32",
                        },
                        "uvs_binary": {
                            "path": str(uvs_output_path),
                            "count": 5,
                            "components": 2,
                            "type": "f64",
                        },
                        "changed_vertices_binary": {
                            "path": str(changed_vertices_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "normals_binary": {
                            "path": str(normals_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangents_binary": {
                            "path": str(tangents_output_path),
                            "count": 5,
                            "components": 3,
                            "type": "f64",
                        },
                        "tangent_signs_binary": {
                            "path": str(tangent_signs_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "f64",
                        },
                        "bone_counts_binary": {
                            "path": str(bone_counts_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_indices_binary": {
                            "path": str(bone_indices_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "bone_weights_binary": {
                            "path": str(bone_weights_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "f64",
                        },
                        "source_vertex_map_binary": {
                            "path": str(source_vertex_map_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                        "source_vertex_offsets_binary": {
                            "path": str(source_vertex_offsets_output_path),
                            "count": 5,
                            "components": 1,
                            "type": "i32",
                        },
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            changed = mesh_native_core.apply_native_mesh_auto_uv(mesh, {0}, resolution=256, allow_topology_change=True)

        self.assertEqual({0: {0, 1, 2, 3, 4}}, changed)
        self.assertEqual(5, len(submesh.vertices))
        self.assertEqual(submesh.vertices[2], submesh.vertices[3])
        self.assertEqual([(0, 1, 2), (3, 1, 4)], submesh.faces)
        self.assertEqual((0.25, 0.25), submesh.uvs[3])
        self.assertEqual((1.0, 0.0, 0.0), submesh.normals[3])
        self.assertEqual((0.0, 0.0, 1.0), submesh.tangents[3])
        self.assertEqual(1.0, submesh.tangent_signs[3])
        self.assertEqual((2,), submesh.bone_indices[3])
        self.assertEqual(12, submesh.source_vertex_map[3])
        self.assertEqual(120, submesh.source_vertex_offsets[3])
        self.assertEqual("xatlas", submesh.auto_uv_report["unwrap_backend"])

    def test_native_auto_uv_report_trusts_changed_descriptor_without_python_compare(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        submesh = mesh.submeshes[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            vertices_path = temp_root / "vertices.bin"
            remap_path = temp_root / "remap.bin"
            faces_path = temp_root / "faces.bin"
            uvs_path = temp_root / "uvs.bin"
            changed_path = temp_root / "changed.bin"
            vertices = array("d")
            for vertex in submesh.vertices:
                vertices.extend(vertex)
            vertices_path.write_bytes(vertices.tobytes())
            remap_path.write_bytes(array("i", (0, 1, 2, 3)).tobytes())
            faces_path.write_bytes(array("i", (0, 1, 2, 2, 1, 3)).tobytes())
            uvs = array("d")
            for uv in ((0.0, 0.0), (1.25, 0.0), (0.0, 1.0), (1.0, 1.0)):
                uvs.extend(uv)
            uvs_path.write_bytes(uvs.tobytes())
            changed_path.write_bytes(array("i", (1,)).tobytes())
            report = {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "auto_uv",
                "unwrap_backend": "xatlas",
                "topology_changed": False,
                "submeshes": [
                    {
                        "index": 0,
                        "status": "ok",
                        "unwrap_backend": "xatlas",
                        "topology_changed": False,
                        "input_vertex_count": 4,
                        "output_vertex_count": 4,
                        "input_face_count": 2,
                        "output_face_count": 2,
                        "chart_count": 1,
                        "vertices_binary": {"path": str(vertices_path), "count": 4, "components": 3, "type": "f64"},
                        "vertex_remap_binary": {"path": str(remap_path), "count": 4, "components": 1, "type": "i32"},
                        "faces_binary": {"path": str(faces_path), "count": 2, "components": 3, "type": "i32"},
                        "uvs_binary": {"path": str(uvs_path), "count": 4, "components": 2, "type": "f64"},
                        "changed_vertices_binary": {"path": str(changed_path), "count": 1, "components": 1, "type": "i32"},
                    }
                ],
            }
            with patch("cdmw.modding.mesh_native_core._vec2", side_effect=AssertionError("native auto-uv changed descriptor should avoid Python UV compare")):
                changed = mesh_native_core._apply_auto_uv_report(mesh, report)

        self.assertEqual({0: {1}}, changed)
        self.assertEqual((1.25, 0.0), submesh.uvs[1])

    def test_native_auto_uv_report_preserves_full_range_changed_vertices(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        report = {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "auto_uv",
            "submeshes": [
                {
                    "index": 0,
                    "status": "ok",
                    "unwrap_backend": "xatlas",
                    "topology_changed": False,
                    "input_vertex_count": 4,
                    "output_vertex_count": 4,
                    "input_face_count": 2,
                    "output_face_count": 2,
                    "chart_count": 1,
                    "vertex_remap": [0, 1, 2, 3],
                    "uvs": [(0.0, 0.0), (1.25, 0.0), (0.0, 1.0), (1.0, 1.0)],
                    "faces": [(0, 1, 2), (1, 3, 2)],
                }
            ],
        }

        changed = mesh_native_core._apply_auto_uv_report(mesh, report)

        self.assertIsInstance(changed[0], range)  # type: ignore[index]
        self.assertEqual(range(0, 4), changed[0])  # type: ignore[index]

    def test_uv_transform_auto_uv_is_undoable_through_mesh_service(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        mesh = _quad_mesh()
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * len(mesh.submeshes[0].vertices)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"auto-uv-undo-{uuid4().hex}", mode="edit")
        original_vertices = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
        original_uvs = tuple(service.working_mesh(view.session_id).submeshes[0].uvs)
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("auto_uv must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "uv_transform",
                        selection=MeshEditSelection.from_maps(source_indices=(0,)),
                        params={"auto_uv": True, "allow_topology_change": True},
                        mode="edit",
                    ),
                )
                after_apply = service.working_mesh(view.session_id).submeshes[0]
                applied_vertices = tuple(after_apply.vertices)
                applied_uvs = tuple(after_apply.uvs)
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[0]
                undo_vertices = tuple(after_undo.vertices)
                undo_uvs = tuple(after_undo.uvs)
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[0]
                redo_vertices = tuple(after_redo.vertices)
                redo_uvs = tuple(after_redo.uvs)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertNotEqual(original_uvs, applied_uvs)
        self.assertTrue(undo.ok)
        self.assertEqual(original_vertices, undo_vertices)
        self.assertEqual(original_uvs, undo_uvs)
        self.assertTrue(redo.ok)
        self.assertEqual(applied_vertices, redo_vertices)
        self.assertEqual(applied_uvs, redo_uvs)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_uv_transform_can_rotate_selected_uvs_around_pivot(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-rotate", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"rotate": 90.0, "pivot": (0.5, 0.5)}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 3)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(1.0, uvs[1][0], places=6)
        self.assertAlmostEqual(1.0, uvs[1][1], places=6)
        self.assertAlmostEqual(0.0, uvs[2][0], places=6)
        self.assertAlmostEqual(0.0, uvs[2][1], places=6)

    def test_uv_transform_flip_uses_explicit_pivot(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-flip-pivot", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"flip_u": True, "flip_v": True, "pivot": (0.25, 0.25)}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual((-0.5, 0.5), uvs[1])
        self.assertEqual((0.5, -0.5), uvs[2])

    def test_uv_transform_does_not_merge_disconnected_overlapping_uv_islands(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_overlapping_uv_island_mesh(), session_id="uv-overlap-island", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"uv_island": True, "offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[0])
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])
        self.assertEqual((0.25, 1.0), mesh.submeshes[0].uvs[2])
        self.assertEqual((0.0, 0.0), mesh.submeshes[0].uvs[3])
        self.assertEqual((1.0, 0.0), mesh.submeshes[0].uvs[4])
        self.assertEqual((0.0, 1.0), mesh.submeshes[0].uvs[5])

    def test_uv_transform_noops_without_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-no-selection", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", params={"offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, state.revision)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))

    def test_uv_transform_noops_when_selected_uvs_do_not_change(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-identity", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"offset": (0.0, 0.0), "scale": (1.0, 1.0), "rotate": 0.0}),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_uv_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=selection,
                params={
                    "offset": (float("inf"), 0.0),
                    "scale": (float("nan"), 1.0),
                    "pivot": (float("inf"), float("nan")),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))

    def test_transform_can_apply_mirror_aware_vertex_drag_through_service(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mirror", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (0.25, 0.0, 0.0),
                    "mirror_x": True,
                    "mirror_pairs_by_submesh": {0: {0: 1, 1: 0}},
                    "recompute_normals": False,
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((0.75, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_transform_can_skip_normal_recompute_for_live_preview_drag(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="live-transform-no-normal", mode="edit")
        mesh = service.working_mesh(view.session_id)
        mesh.submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.0, 0.0, 0.25), "recompute_normals": False, "record_history": False},
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, service.working_mesh(view.session_id).submeshes[0].normals)

    def test_native_transform_preserves_range_changed_vertices_through_service_result(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_large_mesh_for_native_fallback_guard(), session_id="native-range-result", mode="edit")

        def native_transform(mesh: ParsedMesh, **_kwargs: object) -> dict[int, range]:
            submesh = mesh.submeshes[0]
            submesh.vertices = [(x, y, z + 0.25) for x, y, z in submesh.vertices]
            submesh.vertex_count = len(submesh.vertices)
            return {0: range(0, len(submesh.vertices))}

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform_selection", side_effect=native_transform):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "transform",
                    selection=MeshEditSelection.from_maps(source_indices=(0,)),
                    params={"translate": (0.0, 0.0, 0.25), "recompute_normals": False, "record_history": False},
                ),
            )

        changed = dict(result.changed_vertices_by_submesh)[0]
        vertex_count = len(service.working_mesh(view.session_id).submeshes[0].vertices)
        self.assertTrue(result.ok)
        self.assertIsInstance(changed, range)
        self.assertEqual(range(0, vertex_count), changed)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="transform-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (float("inf"), 0.0, 0.0),
                    "scale": (float("nan"), 1.0, 1.0),
                    "rotate": (0.0, 0.0, float("inf")),
                    "pivot": (float("nan"), 0.0, 0.0),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))

    def test_transform_can_rotate_and_scale_selected_vertices_through_service(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="rotate-scale", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "pivot": (0.0, 0.0, 0.0),
                    "scale": (2.0, 1.0, 1.0),
                    "rotate": (0.0, 0.0, 90.0),
                    "translate": (1.0, 1.0, 0.0),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, range(1, 2)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(1.0, mesh.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(3.0, mesh.submeshes[0].vertices[1][1], places=6)
        self.assertAlmostEqual(0.0, mesh.submeshes[0].vertices[2][0], places=6)
        self.assertAlmostEqual(1.0, mesh.submeshes[0].vertices[2][1], places=6)

    def test_transform_can_constrain_axis_and_snap_to_increment(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="axis-snap", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)})

        moved = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.26, 0.26, 0.26), "axis": "z", "snap": 0.25},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(moved.ok)
        changed = dict(moved.changed_vertices_by_submesh)[0]
        self.assertIsInstance(changed, dict)
        self.assertEqual(2, changed["changed_vertices_binary"]["count"])  # type: ignore[index]
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.25), mesh.submeshes[0].vertices[3])

        scaled = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (3,)}),
                params={"pivot": (0.0, 0.0, 0.0), "scale": (2.0, 2.0, 2.0), "axis": "x"},
            ),
        )

        self.assertTrue(scaled.ok)
        self.assertEqual((2.0, 1.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[3])

    def test_edge_split_can_split_selected_edge_seam(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="edge-split", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})

        result = service.apply_command(view.session_id, MeshEditCommand("edge_split", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(4, 6)),), result.changed_vertices_by_submesh)
        self.assertEqual(6, len(submesh.vertices))
        self.assertEqual(6, len(submesh.uvs))
        self.assertEqual((0, 1, 2), submesh.faces[0])
        self.assertEqual((4, 3, 5), submesh.faces[1])

    def test_edge_split_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-edge-split", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})
        calls: list[tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[tuple[int, int]]], bool]] = []

        def native_edge_split(
            target_mesh: ParsedMesh,
            selected_faces_by_submesh: dict[int, set[int]],
            selected_vertices_by_submesh: dict[int, set[int]] | None = None,
            *,
            selected_edges_by_submesh: dict[int, set[tuple[int, int]]] | None = None,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> tuple[set[int], dict[int, set[int]]]:
            calls.append(
                (
                    {index: set(values) for index, values in selected_faces_by_submesh.items()},
                    {index: set(values) for index, values in (selected_vertices_by_submesh or {}).items()},
                    {index: set(values) for index, values in (selected_edges_by_submesh or {}).items()},
                    recompute_normals,
                )
            )
            target = target_mesh.submeshes[0]
            target.vertices.extend((target.vertices[1], target.vertices[2]))
            target.uvs.extend((target.uvs[1], target.uvs[2]))
            target.faces = [(0, 1, 2), (4, 3, 5)]
            target.vertex_count = len(target.vertices)
            target.face_count = len(target.faces)
            return {0}, {0: {4, 5}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_edge_split", side_effect=AssertionError("legacy edge split helper")),
            patch("cdmw.modding.mesh_edit_ops._valid_face_items", side_effect=AssertionError("python edge split loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("edge_split", selection=selection))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(4, 6)),), result.changed_vertices_by_submesh)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], working.submeshes[0].faces)
        self.assertEqual([(0, 1, 2), (4, 3, 5)], service.working_mesh(view.session_id).submeshes[0].faces)

    def test_bridge_connects_loose_edges_and_rejects_already_filled_pairs(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="bridge", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})

        result = service.apply_command(view.session_id, MeshEditCommand("bridge", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(2, len(submesh.faces))
        self.assertEqual((0, 1, 3), submesh.faces[-2])
        self.assertEqual((0, 3, 2), submesh.faces[-1])

        filled_view = service.open_edit_session(_quad_mesh(), session_id="bridge-filled", mode="edit")
        rejected = service.apply_command(filled_view.session_id, MeshEditCommand("bridge", selection=selection))
        filled_submesh = service.working_mesh(filled_view.session_id).submeshes[0]

        self.assertTrue(rejected.ok)
        self.assertFalse(rejected.topology_changed)
        self.assertEqual((), rejected.affected_submesh_indices)
        self.assertEqual(2, filled_submesh.face_count)
        self.assertEqual(0, service.session_view(filled_view.session_id).revision)

    def test_bridge_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="native-bridge", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_bridge", side_effect=AssertionError("legacy bridge helper")),
            patch("cdmw.modding.mesh_edit_ops._valid_face_items", side_effect=AssertionError("python bridge loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("bridge", selection=selection))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([], working.submeshes[0].faces)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], service.working_mesh(view.session_id).submeshes[0].faces)
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)

    def test_fill_uses_explicit_vertices_and_edges_without_expanding_face_selection(self) -> None:
        service = MeshService()
        edge_view = service.open_edit_session(_quad_mesh(), session_id="fill-edge", mode="edit")

        filled = service.apply_command(
            edge_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (0, 3))})),
        )

        edge_submesh = service.working_mesh(edge_view.session_id).submeshes[0]
        self.assertTrue(filled.ok)
        self.assertTrue(filled.topology_changed)
        self.assertEqual((0,), filled.affected_submesh_indices)
        self.assertEqual(3, edge_submesh.face_count)
        self.assertEqual((0, 1, 3), edge_submesh.faces[-1])

        quad_view = service.open_edit_session(_loose_edge_mesh(), session_id="fill-quad-loop", mode="edit")
        quad_fill = service.apply_command(
            quad_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (2, 3), (0, 2))})),
        )
        quad_submesh = service.working_mesh(quad_view.session_id).submeshes[0]

        self.assertTrue(quad_fill.ok)
        self.assertTrue(quad_fill.topology_changed)
        self.assertEqual(2, quad_submesh.face_count)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], quad_submesh.faces)

        face_view = service.open_edit_session(_quad_mesh(), session_id="fill-face-noop", mode="edit")
        face_fill = service.apply_command(
            face_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}, source_indices=(0,))),
        )

        face_submesh = service.working_mesh(face_view.session_id).submeshes[0]
        self.assertTrue(face_fill.ok)
        self.assertFalse(face_fill.topology_changed)
        self.assertEqual((), face_fill.affected_submesh_indices)
        self.assertEqual(2, face_submesh.face_count)
        self.assertEqual(0, service.session_view(face_view.session_id).revision)

        existing_view = service.open_edit_session(_quad_mesh(), session_id="fill-existing-noop", mode="edit")
        existing_fill = service.apply_command(
            existing_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2), (0, 2))})),
        )
        existing_quad = service.apply_command(
            existing_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})),
        )
        existing_submesh = service.working_mesh(existing_view.session_id).submeshes[0]
        self.assertTrue(existing_fill.ok)
        self.assertFalse(existing_fill.topology_changed)
        self.assertTrue(existing_quad.ok)
        self.assertFalse(existing_quad.topology_changed)
        self.assertEqual(2, existing_submesh.face_count)
        self.assertEqual(0, service.session_view(existing_view.session_id).revision)

    def test_loop_cut_uses_native_mesh_core_before_python_fallback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="native-loop-cut", mode="edit")
        working = service.working_mesh(view.session_id, clone=False)
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})
        calls: list[tuple[dict[int, set[tuple[int, int]]], dict[str, object], bool]] = []

        def native_loop_cut(
            target_mesh: ParsedMesh,
            selected_edges_by_submesh: dict[int, set[tuple[int, int]]],
            params: dict[str, object] | None = None,
            *,
            recompute_normals: bool = True,
            **_kwargs: object,
        ) -> tuple[set[int], dict[int, set[int]]]:
            calls.append(
                (
                    {index: set(edges) for index, edges in selected_edges_by_submesh.items()},
                    dict(params or {}),
                    recompute_normals,
                )
            )
            target = target_mesh.submeshes[0]
            target.vertices.append((0.25, 0.0, 0.0))
            target.uvs.append((0.25, 0.0))
            target.faces = [(0, 3, 2), (3, 1, 2)]
            target.vertex_count = len(target.vertices)
            target.face_count = len(target.faces)
            return {0}, {0: {3}}

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_loop_cut", side_effect=AssertionError("legacy loop cut helper")),
            patch("cdmw.modding.mesh_edit_ops._edge_cut_faces", side_effect=AssertionError("python loop cut reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection, params={"factor": 0.25}))

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(3, 4)),), result.changed_vertices_by_submesh)
        self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)
        self.assertEqual([(0, 1, 2)], working.submeshes[0].faces)
        self.assertEqual([(0, 3, 2), (3, 1, 2)], service.working_mesh(view.session_id).submeshes[0].faces)

    def test_loop_cut_can_split_selected_edge_with_midpoint(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="loop-cut", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(4, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, len(submesh.vertices))
        self.assertEqual(5, len(submesh.uvs))
        self.assertEqual((0.5, 0.5, 0.0), submesh.vertices[4])
        self.assertEqual((0.5, 0.5), submesh.uvs[4])
        self.assertEqual(4, len(submesh.faces))
        self.assertTrue(all(set(face) & {4} for face in submesh.faces))

    def test_loop_cut_can_create_multiple_cuts_on_selected_edge(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-multi", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection, params={"cuts": 2}))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(3, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, submesh.vertex_count)
        self.assertEqual(3, submesh.face_count)
        self.assertAlmostEqual(1.0 / 3.0, submesh.vertices[3][0], places=6)
        self.assertAlmostEqual(2.0 / 3.0, submesh.vertices[4][0], places=6)
        self.assertEqual((1.0 / 3.0, 0.0), submesh.uvs[3])
        self.assertEqual((2.0 / 3.0, 0.0), submesh.uvs[4])
        self.assertEqual([(0, 3, 2), (3, 4, 2), (4, 1, 2)], submesh.faces)

    def test_loop_cut_can_place_single_cut_at_factor(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-factor", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection, params={"factor": 0.25}))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(3, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual((0.25, 0.0, 0.0), submesh.vertices[3])
        self.assertEqual((0.25, 0.0), submesh.uvs[3])
        self.assertEqual([(0, 3, 2), (3, 1, 2)], submesh.faces)

    def test_loop_cut_two_edges_only_splits_selected_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-two-edges", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2))})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, range(3, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, submesh.vertex_count)
        self.assertEqual(3, submesh.face_count)
        self.assertEqual((0.5, 0.0, 0.0), submesh.vertices[3])
        self.assertEqual((0.5, 0.5, 0.0), submesh.vertices[4])
        self.assertEqual([(3, 1, 4), (0, 3, 4), (0, 4, 2)], submesh.faces)

    def test_weld_only_merges_selected_vertices_within_threshold(self) -> None:
        service = MeshService()
        distant_view = service.open_edit_session(_quad_mesh(), session_id="weld-distant", mode="edit")

        distant = service.apply_command(
            distant_view.session_id,
            MeshEditCommand("weld", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})),
        )

        distant_submesh = service.working_mesh(distant_view.session_id).submeshes[0]
        self.assertTrue(distant.ok)
        self.assertFalse(distant.topology_changed)
        self.assertEqual(4, distant_submesh.vertex_count)
        self.assertEqual(2, distant_submesh.face_count)
        self.assertEqual(0, service.session_view(distant_view.session_id).revision)

        duplicate_view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="weld-duplicate", mode="edit")
        welded = service.apply_command(
            duplicate_view.session_id,
            MeshEditCommand("weld", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)}), params={"threshold": 0.001}),
        )

        duplicate_submesh = service.working_mesh(duplicate_view.session_id).submeshes[0]
        self.assertTrue(welded.ok)
        self.assertTrue(welded.topology_changed)
        self.assertEqual((0,), welded.affected_submesh_indices)
        self.assertEqual((), welded.changed_vertices_by_submesh)
        self.assertEqual(4, duplicate_submesh.vertex_count)
        self.assertEqual(2, duplicate_submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], duplicate_submesh.faces)

    def test_merge_uses_native_mesh_core_before_python_fallback(self) -> None:
        mesh = _duplicate_vertex_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-merge", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_merge", side_effect=AssertionError("legacy merge helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python merge loop reached")),
        ):
            result = service.apply_command(view.session_id, MeshEditCommand("merge", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)

    def test_weld_uses_native_mesh_core_before_python_fallback(self) -> None:
        mesh = _duplicate_vertex_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="native-weld", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})

        with (
            patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_weld", side_effect=AssertionError("legacy weld helper")),
            patch("cdmw.modding.mesh_edit_ops._selected_vertices", side_effect=AssertionError("python weld loop reached")),
        ):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("weld", selection=selection, params={"threshold": 0.001}),
            )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)

    def test_compacting_topology_actions_do_not_emit_stale_vertex_deltas(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="merge-compact", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("merge", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)

    def test_all_named_v1_actions_return_results(self) -> None:
        actions = tuple(
            action
            for action in MESH_EDIT_ACTIONS
            if action not in {"triangulate_display", "quadrangulate_display"}
        )
        for action in actions:
            with self.subTest(action=action):
                service = MeshService()
                view = service.open_edit_session(_quad_mesh(two_parts=True), session_id=action, mode="edit")
                selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
                command = MeshEditCommand(action, selection=selection, mode="sculpt" if action == "set_mode" else None)
                if action == "material_copy":
                    command = MeshEditCommand(action, selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0})
                result = service.apply_command(view.session_id, command)
                self.assertIn(result.status, {"ok", "noop"})

    def test_selection_normalizes_invalid_indices(self) -> None:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (2, 2, -1, "bad", True, 1.9, float("inf")), True: (7,), 0.5: (8,)},  # type: ignore[dict-item]
            edges_by_submesh={0: ((3, 1), (1, 3), (4, "bad"), (True, 2), (1.9, 3))},  # type: ignore[list-item]
            faces_by_submesh={1: (5, "bad", True, 1.9, float("nan"))},
            source_indices=(2, -1, "bad", True, 1.9, float("inf")),
        )

        self.assertEqual({0: {2}}, selection.vertex_map())
        self.assertEqual({0: {(1, 3)}}, selection.edge_map())
        self.assertEqual({1: {5}}, selection.face_map())
        self.assertEqual((2,), selection.source_indices)

    def test_selection_normalizes_malformed_payload_shapes(self) -> None:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: 2, 1: None, 2: ("4", "bad"), "bad": (9,)},  # type: ignore[arg-type]
            edges_by_submesh={0: (3, 1), 1: (None, (4, "bad"), [7, 5], "12", object())},  # type: ignore[arg-type]
            faces_by_submesh={0: 1, 1: ("2", "bad"), "bad": (3,)},  # type: ignore[arg-type]
            source_indices=5,  # type: ignore[arg-type]
        )
        empty = MeshEditSelection.from_maps(
            vertices_by_submesh=42,  # type: ignore[arg-type]
            edges_by_submesh=42,  # type: ignore[arg-type]
            faces_by_submesh=42,  # type: ignore[arg-type]
            source_indices=object(),  # type: ignore[arg-type]
        )

        self.assertEqual({0: {2}, 2: {4}}, selection.vertex_map())
        self.assertEqual({0: {(1, 3)}, 1: {(5, 7)}}, selection.edge_map())
        self.assertEqual({0: {1}, 1: {2}}, selection.face_map())
        self.assertEqual((5,), selection.source_indices)
        self.assertTrue(empty.is_empty())


if __name__ == "__main__":
    unittest.main()
