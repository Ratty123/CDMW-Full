import copy
import unittest

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    assert_mesh_topology_unchanged,
    build_vertex_adjacency,
    build_x_mirror_pairs,
    mesh_topology_signature,
    recompute_submesh_normals,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _submesh() -> SubMesh:
    return SubMesh(
        name="quad",
        material="quad",
        vertices=[
            (-1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (-1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        faces=[(0, 1, 2), (1, 3, 2)],
    )


class MeshDeformerTests(unittest.TestCase):
    def test_grab_preserves_topology_and_recomputes_normals(self) -> None:
        mesh = ParsedMesh(format="obj", submeshes=[_submesh()])
        before = mesh_topology_signature(mesh)

        changed = apply_brush_deformation(
            mesh.submeshes[0],
            tool="grab",
            center=(-1.0, 0.0, 0.0),
            radius=0.5,
            strength=1.0,
            drag_delta=(0.0, 0.0, 0.5),
        )

        self.assertIn(0, changed)
        self.assertEqual((-1.0, 0.0, 0.5), mesh.submeshes[0].vertices[0])
        self.assertEqual(len(mesh.submeshes[0].normals), len(mesh.submeshes[0].vertices))
        assert_mesh_topology_unchanged(before, mesh)

    def test_vertex_delta_mirrors_x_axis(self) -> None:
        sm = _submesh()

        changed = apply_vertex_delta(sm, [0], (0.25, 0.0, 0.0), mirror_x=True)

        self.assertIn(0, changed)
        self.assertIn(1, changed)
        self.assertEqual((-0.75, 0.0, 0.0), sm.vertices[0])
        self.assertEqual((0.75, 0.0, 0.0), sm.vertices[1])

    def test_smooth_moves_affected_vertex_without_topology_change(self) -> None:
        sm = _submesh()
        mesh = ParsedMesh(format="obj", submeshes=[copy.deepcopy(sm)])
        before = mesh_topology_signature(mesh)
        mesh.submeshes[0].vertices[0] = (-1.0, -1.0, 0.0)

        changed = apply_brush_deformation(
            mesh.submeshes[0],
            tool="smooth",
            center=(-1.0, -1.0, 0.0),
            radius=0.25,
            strength=0.5,
            vertex_indices=[0],
        )

        self.assertEqual([0], changed)
        self.assertGreater(mesh.submeshes[0].vertices[0][1], -1.0)
        self.assertEqual(before.vertex_counts, mesh_topology_signature(mesh).vertex_counts)
        self.assertEqual(before.face_counts, mesh_topology_signature(mesh).face_counts)

    def test_smooth_can_reuse_cached_adjacency(self) -> None:
        sm = _submesh()
        sm.vertices[0] = (-1.0, -1.0, 0.0)
        adjacency = build_vertex_adjacency(sm)

        changed = apply_brush_deformation(
            sm,
            tool="smooth",
            center=(-1.0, -1.0, 0.0),
            radius=0.25,
            strength=0.5,
            vertex_indices=[0],
            adjacency=adjacency,
            recompute_normals=False,
        )

        self.assertEqual([0], changed)
        self.assertGreater(sm.vertices[0][1], -1.0)

    def test_x_mirror_pairs_find_opposite_vertices(self) -> None:
        pairs = build_x_mirror_pairs(_submesh().vertices)

        self.assertEqual(1, pairs[0])
        self.assertEqual(0, pairs[1])

    def test_live_vertex_delta_can_defer_normal_recompute(self) -> None:
        sm = _submesh()
        sm.normals = [(0.0, 1.0, 0.0)] * len(sm.vertices)
        before_normals = list(sm.normals)

        changed = apply_vertex_delta(sm, [0], (0.0, 0.0, 0.25), recompute_normals=False)

        self.assertEqual([0], changed)
        self.assertEqual(before_normals, sm.normals)
        recompute_submesh_normals(sm)
        self.assertEqual(len(sm.normals), len(sm.vertices))

    def test_live_grab_total_drag_matches_release_delta(self) -> None:
        live = _submesh()
        release = _submesh()

        apply_vertex_delta(live, [0], (0.1, 0.0, 0.0), recompute_normals=False)
        live = _submesh()
        apply_vertex_delta(live, [0], (0.25, 0.0, 0.0), recompute_normals=False)
        apply_vertex_delta(release, [0], (0.25, 0.0, 0.0), recompute_normals=False)

        self.assertEqual(release.vertices, live.vertices)

    def test_inverted_inflate_moves_opposite_direction(self) -> None:
        outward = _submesh()
        inward = _submesh()

        apply_brush_deformation(
            outward,
            tool="inflate",
            center=(-1.0, 0.0, 0.0),
            radius=0.5,
            strength=1.0,
            amount=0.2,
            vertex_indices=[0],
            recompute_normals=False,
        )
        apply_brush_deformation(
            inward,
            tool="inflate",
            center=(-1.0, 0.0, 0.0),
            radius=0.5,
            strength=1.0,
            amount=0.2,
            vertex_indices=[0],
            invert=True,
            recompute_normals=False,
        )

        self.assertGreater(outward.vertices[0][2], 0.0)
        self.assertLess(inward.vertices[0][2], 0.0)

    def test_brush_can_use_explicit_vertex_weights_for_screen_space_radius(self) -> None:
        sm = _submesh()

        changed = apply_brush_deformation(
            sm,
            tool="grab",
            center=(50.0, 50.0, 50.0),
            radius=0.001,
            strength=1.0,
            drag_delta=(0.0, 0.0, 1.0),
            vertex_indices=[0, 1, 2],
            vertex_weights={0: 1.0, 1: 0.5, 2: 0.25},
            recompute_normals=False,
        )

        self.assertEqual([0, 1, 2], changed)
        self.assertEqual(1.0, sm.vertices[0][2])
        self.assertEqual(0.5, sm.vertices[1][2])
        self.assertEqual(0.25, sm.vertices[2][2])


if __name__ == "__main__":
    unittest.main()
