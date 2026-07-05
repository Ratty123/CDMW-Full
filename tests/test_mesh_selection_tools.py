from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    grow_vertex_selection,
    invert_vertex_selection,
    select_all_vertex_selection,
    shrink_vertex_selection,
    smooth_vertex_selection,
    split_faces_to_submesh,
    subdivide_faces_touching_vertices,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _quad_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="quad",
        material="quad",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    return ParsedMesh(path="quad.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=2)

class MeshSelectionToolTests(unittest.TestCase):
    def test_grow_selection_adds_adjacent_vertices(self) -> None:
        self.assertEqual({0: {0, 1, 2}}, grow_vertex_selection(_quad_mesh(), {0: {0}}))

    def test_grow_selection_uses_native_mesh_core_when_available(self) -> None:
        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-json", command)
            self.assertEqual("selection", payload["operation"])  # type: ignore[index]
            self.assertEqual("grow", payload["selection"]["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(4, submesh_payload["vertex_count"])
            self.assertIn("faces_binary", submesh_payload)
            self.assertEqual(0, submesh_payload["selected_vertex_start"])
            self.assertEqual(1, submesh_payload["selected_vertex_count"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("vertices", submesh_payload)
            self.assertNotIn("faces", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            self.assertTrue(Path(submesh_payload["faces_binary"]["path"]).is_file())
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection",
                "submeshes": [{"index": 0, "selected_vertex_start": 0, "selected_vertex_count": 3}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            self.assertEqual({0: {0, 1, 2}}, grow_vertex_selection(_quad_mesh(), {0: {0}}))

    def test_invert_selection_uses_native_mesh_core_without_python_all_vertex_set(self) -> None:
        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-json", command)
            self.assertEqual("selection", payload["operation"])  # type: ignore[index]
            self.assertEqual("invert", payload["selection"]["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(4, submesh_payload["vertex_count"])
            self.assertIn("faces_binary", submesh_payload)
            self.assertIn("selected_vertices_binary", submesh_payload)
            self.assertEqual(2, submesh_payload["selected_vertices_binary"]["count"])
            self.assertNotIn("selected_all_vertices", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection",
                "submeshes": [{"index": 0, "selected_vertices": [1, 2]}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            self.assertEqual(
                {0: {1, 2}},
                invert_vertex_selection(_quad_mesh(), {0: {0, 3}}, source_indices=(0,)),
            )

    def test_invert_selection_falls_back_to_requested_scope_only(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes.append(_quad_mesh().submeshes[0])
        with patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=None):
            self.assertEqual(
                {1: {0, 2, 3}},
                invert_vertex_selection(mesh, {1: {1}}, source_indices=(1,)),
            )

    def test_invert_selection_blocks_python_expansion_when_native_fails(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.apply_native_mesh_selection", return_value=None),
                patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
            ):
                self.assertEqual({}, invert_vertex_selection(_quad_mesh(), {0: {0}}, source_indices=(0,)))
                self.assertEqual({"selection.invert.blocked": 1}, mesh_native_core.native_mesh_core_fallback_counts())
        finally:
            mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_select_all_selection_uses_native_mesh_core_all_operation(self) -> None:
        def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
            self.assertEqual("selection-json", command)
            self.assertEqual("all", payload["selection"]["operation"])  # type: ignore[index]
            submesh_payload = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(4, submesh_payload["vertex_count"])
            self.assertTrue(submesh_payload["selected_all_vertices"])
            self.assertNotIn("selected_vertices_binary", submesh_payload)
            self.assertNotIn("selected_vertices", submesh_payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "operation": "selection",
                "submeshes": [{"index": 0, "selected_vertices": [0, 1, 2, 3]}],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        ):
            self.assertEqual({0: {0, 1, 2, 3}}, select_all_vertex_selection(_quad_mesh(), (0,)))

    def test_select_all_selection_falls_back_to_requested_scope_only(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes.append(_quad_mesh().submeshes[0])
        with patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=None):
            self.assertEqual({1: {0, 1, 2, 3}}, select_all_vertex_selection(mesh, (1,)))

    def test_select_all_selection_blocks_python_expansion_when_native_fails(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.apply_native_mesh_selection", return_value=None),
                patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
            ):
                self.assertEqual({}, select_all_vertex_selection(_quad_mesh(), (0,)))
                self.assertEqual({"selection.select_all.blocked": 1}, mesh_native_core.native_mesh_core_fallback_counts())
        finally:
            mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_grow_shrink_smooth_block_python_expansion_when_native_fails(self) -> None:
        from cdmw.modding import mesh_native_core

        operations = (
            (grow_vertex_selection, {"steps": 1}, "selection.grow.blocked"),
            (shrink_vertex_selection, {"steps": 1}, "selection.shrink.blocked"),
            (smooth_vertex_selection, {"iterations": 1}, "selection.smooth.blocked"),
        )
        for operation, kwargs, fallback_key in operations:
            with self.subTest(fallback_key=fallback_key):
                mesh_native_core.clear_native_mesh_core_fallback_counts()
                try:
                    with (
                        patch("cdmw.modding.mesh_native_core.apply_native_mesh_selection", return_value=None),
                        patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                        patch(
                            "cdmw.modding.mesh_deformer.build_vertex_adjacency",
                            side_effect=AssertionError("python adjacency fallback ran"),
                        ),
                    ):
                        self.assertEqual({}, operation(_quad_mesh(), {0: {0}}, **kwargs))
                        self.assertEqual({fallback_key: 1}, mesh_native_core.native_mesh_core_fallback_counts())
                finally:
                    mesh_native_core.clear_native_mesh_core_fallback_counts()

    def test_shrink_selection_erodes_boundary_vertices(self) -> None:
        self.assertEqual({0: {0}}, shrink_vertex_selection(_quad_mesh(), {0: {0, 1, 2}}))

    def test_smooth_selection_removes_isolated_and_fills_dense_neighbors(self) -> None:
        mesh = _quad_mesh()
        self.assertEqual({}, smooth_vertex_selection(mesh, {0: {0}}))
        self.assertEqual({0: {0, 1, 2, 3}}, smooth_vertex_selection(mesh, {0: {0, 1, 2}}))

    def test_deformation_helpers_return_changed_vertex_indices_for_live_updates(self) -> None:
        submesh = _quad_mesh().submeshes[0]

        moved = apply_vertex_delta(submesh, [0, 3], (0.5, 0.0, 0.0), recompute_normals=False)
        self.assertEqual([0, 3], moved)
        self.assertEqual((0.5, 0.0, 0.0), submesh.vertices[0])
        self.assertEqual((1.5, 1.0, 0.0), submesh.vertices[3])

        brushed = apply_brush_deformation(
            submesh,
            tool="grab",
            center=(0.0, 0.0, 0.0),
            radius=2.0,
            strength=1.0,
            drag_delta=(0.0, 0.0, 1.0),
            vertex_indices=[1],
            vertex_weights={1: 0.5},
            recompute_normals=False,
        )
        self.assertEqual([1], brushed)
        self.assertEqual((1.0, 0.0, 0.5), submesh.vertices[1])

    def test_smooth_relax_uses_iterations_and_returns_changed_indices(self) -> None:
        submesh = SubMesh(
            name="bump",
            material="bump",
            vertices=[
                (0.0, 0.0, 1.0),
                (-1.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 3), (0, 3, 2), (0, 2, 4), (0, 4, 1)],
            vertex_count=5,
            face_count=4,
        )

        changed = apply_brush_deformation(
            submesh,
            tool="smooth",
            center=(0.0, 0.0, 0.0),
            radius=2.0,
            strength=0.5,
            vertex_indices=[0],
            vertex_weights={0: 1.0},
            iterations=3,
            recompute_normals=False,
        )

        self.assertEqual([0], changed)
        self.assertAlmostEqual(0.125, submesh.vertices[0][2], places=6)

    def test_subdivide_selection_splits_touched_faces_for_finer_sculpting(self) -> None:
        mesh = _quad_mesh()

        result = subdivide_faces_touching_vertices(mesh, {0: {0}}, recompute_normals=False)

        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(3, result.added_vertex_count)
        self.assertEqual(3, result.added_face_count)
        self.assertEqual(7, len(mesh.submeshes[0].vertices))
        self.assertEqual(5, len(mesh.submeshes[0].faces))
        self.assertIn(4, (result.changed_vertices_by_submesh or {})[0])

    def test_split_faces_to_submesh_moves_selected_faces_and_preserves_vertex_data(self) -> None:
        mesh = _quad_mesh()
        source = mesh.submeshes[0]
        source.texture = "body.dds"
        source.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        source.normals = [(0.0, 0.0, 1.0)] * 4
        source.bone_indices = [(0,), (1,), (2,), (3,)]
        source.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        source.source_vertex_map = [10, 11, 12, 13]
        source.source_vertex_offsets = [100, 110, 120, 130]

        result = split_faces_to_submesh(mesh, selected_faces_by_submesh={0: {0}}, recompute_normals=False)

        self.assertEqual(0, result.source_submesh_index)
        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual(1, result.moved_face_count)
        self.assertEqual(3, result.moved_vertex_count)
        self.assertEqual([(0, 2, 1)], mesh.submeshes[0].faces)
        self.assertEqual(1, mesh.submeshes[0].face_count)
        self.assertEqual("quad", mesh.submeshes[1].material)
        self.assertEqual("body.dds", mesh.submeshes[1].texture)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[1].faces)
        self.assertEqual([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], mesh.submeshes[1].uvs)
        self.assertEqual([(0.0, 0.0, 1.0)] * 3, mesh.submeshes[1].normals)
        self.assertEqual([(0,), (1,), (2,)], mesh.submeshes[1].bone_indices)
        self.assertEqual([10, 11, 12], mesh.submeshes[1].source_vertex_map)
        self.assertEqual([100, 110, 120], mesh.submeshes[1].source_vertex_offsets)
        self.assertEqual(6, mesh.total_vertices)
        self.assertEqual(2, mesh.total_faces)

    def test_split_faces_to_submesh_uses_vertex_selection_and_rejects_multiple_parts(self) -> None:
        mesh = _quad_mesh()
        result = split_faces_to_submesh(mesh, selected_vertices_by_submesh={0: {3}}, recompute_normals=False)

        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual([(0, 1, 2)], mesh.submeshes[0].faces)
        self.assertEqual([(0, 2, 1)], mesh.submeshes[1].faces)

        mesh = _quad_mesh()
        mesh.submeshes.append(_quad_mesh().submeshes[0])
        with self.assertRaisesRegex(ValueError, "one part"):
            split_faces_to_submesh(mesh, selected_faces_by_submesh={0: {0}, 1: {0}}, recompute_normals=False)


if __name__ == "__main__":
    unittest.main()
