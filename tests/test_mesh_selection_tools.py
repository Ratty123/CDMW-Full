from __future__ import annotations

import unittest

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    grow_vertex_selection,
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
