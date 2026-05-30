from __future__ import annotations

import unittest

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    grow_vertex_selection,
    shrink_vertex_selection,
    smooth_vertex_selection,
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


if __name__ == "__main__":
    unittest.main()
