from __future__ import annotations

import unittest

from cdmw.modding.mesh_deformer import (
    grow_vertex_selection,
    shrink_vertex_selection,
    smooth_vertex_selection,
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


if __name__ == "__main__":
    unittest.main()
