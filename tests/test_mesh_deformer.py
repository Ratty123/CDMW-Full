import copy
import tempfile
import unittest
from pathlib import Path

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    assert_mesh_topology_unchanged,
    build_vertex_adjacency,
    build_x_mirror_pairs,
    compact_orphan_vertices,
    delete_faces_touching_vertices,
    mesh_topology_signature,
    recompute_submesh_normals,
)
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_importer import import_obj
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


def _strip_submesh(rows: int = 6) -> SubMesh:
    vertices = []
    for row in range(rows + 1):
        vertices.append((0.0, float(row), 0.0))
        vertices.append((1.0, float(row), 0.0))
    faces = []
    for row in range(rows):
        a = row * 2
        b = a + 1
        c = a + 2
        d = a + 3
        faces.extend(((a, b, c), (b, d, c)))
    return SubMesh(
        name="cloak_strip",
        material="cloak",
        vertices=vertices,
        faces=faces,
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

    def test_grab_can_defer_normals_without_creating_normal_output(self) -> None:
        sm = _submesh()
        sm.normals = []

        changed = apply_brush_deformation(
            sm,
            tool="grab",
            center=(-1.0, 0.0, 0.0),
            radius=0.5,
            strength=1.0,
            drag_delta=(0.0, 0.0, 0.25),
            recompute_normals=False,
        )

        self.assertEqual([0], changed)
        self.assertEqual([], sm.normals)

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

    def test_delete_faces_touching_selected_vertex_remaps_vertex_aligned_data(self) -> None:
        sm = _submesh()
        sm.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        sm.normals = [(0.0, 0.0, 1.0)] * 4
        sm.bone_indices = [(0,), (1,), (2,), (3,)]
        sm.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        sm.source_vertex_map = [10, 11, 12, 13]
        sm.source_vertex_offsets = [100, 110, 120, 130]
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        result = delete_faces_touching_vertices(mesh, {0: [0]})

        self.assertEqual(1, result.removed_face_count)
        self.assertEqual(1, result.removed_vertex_count)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual([], list(result.emptied_submesh_indices))
        self.assertEqual([(1.0, 0.0, 0.0), (-1.0, 1.0, 0.0), (1.0, 1.0, 0.0)], sm.vertices)
        self.assertEqual([(0, 2, 1)], sm.faces)
        self.assertEqual([(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], sm.uvs)
        self.assertEqual([(1,), (2,), (3,)], sm.bone_indices)
        self.assertEqual([11, 12, 13], sm.source_vertex_map)
        self.assertEqual([110, 120, 130], sm.source_vertex_offsets)
        self.assertEqual(3, mesh.total_vertices)
        self.assertEqual(1, mesh.total_faces)
        self.assertEqual(3, len(sm.normals))

    def test_delete_faces_can_empty_submesh(self) -> None:
        sm = _submesh()
        sm.uvs = [(0.0, 0.0)] * 4
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        result = delete_faces_touching_vertices(mesh, {0: [0, 1, 2, 3]})

        self.assertEqual(2, result.removed_face_count)
        self.assertEqual(4, result.removed_vertex_count)
        self.assertEqual((0,), result.emptied_submesh_indices)
        self.assertEqual([], sm.vertices)
        self.assertEqual([], sm.uvs)
        self.assertEqual([], sm.normals)
        self.assertEqual([], sm.faces)
        self.assertEqual(0, mesh.total_vertices)
        self.assertEqual(0, mesh.total_faces)

    def test_delete_faces_preserves_unrelated_submeshes(self) -> None:
        first = _submesh()
        second = _submesh()
        mesh = ParsedMesh(format="obj", submeshes=[first, copy.deepcopy(second)])

        result = delete_faces_touching_vertices(mesh, {0: [0]})

        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(second.vertices, mesh.submeshes[1].vertices)
        self.assertEqual(second.faces, mesh.submeshes[1].faces)
        self.assertEqual(7, mesh.total_vertices)
        self.assertEqual(3, mesh.total_faces)

    def test_delete_faces_exports_roundtrip_valid_obj(self) -> None:
        sm = _submesh()
        sm.texture = "textures/cloth.png"
        sm.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        mesh = ParsedMesh(path="character/model/cloak.pac", format="pac", submeshes=[sm], total_vertices=4, total_faces=2, has_uvs=True)

        result = delete_faces_touching_vertices(mesh, {0: [0]})

        self.assertEqual(1, result.removed_face_count)
        self.assertEqual(3, mesh.total_vertices)
        self.assertEqual(1, mesh.total_faces)

        with tempfile.TemporaryDirectory() as temp_dir:
            exported_paths = export_obj(mesh, temp_dir, "cloak_trimmed")
            obj_path = Path(exported_paths[0])
            mtl_path = Path(exported_paths[1])

            self.assertTrue(obj_path.is_file())
            self.assertTrue(mtl_path.is_file())
            self.assertIn("map_Kd textures/cloth.png", mtl_path.read_text(encoding="utf-8"))

            imported = import_obj(str(obj_path))

        self.assertEqual("character/model/cloak.pac", imported.path)
        self.assertEqual("pac", imported.format)
        self.assertEqual(1, len(imported.submeshes))
        self.assertEqual(3, imported.total_vertices)
        self.assertEqual(1, imported.total_faces)
        self.assertEqual("textures/cloth.png", imported.submeshes[0].texture)
        for face in imported.submeshes[0].faces:
            self.assertTrue(all(0 <= index < len(imported.submeshes[0].vertices) for index in face))

    def test_live_delete_can_defer_orphan_compaction(self) -> None:
        sm = _submesh()
        sm.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        sm.source_vertex_map = [10, 11, 12, 13]
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        delete_result = delete_faces_touching_vertices(mesh, {0: [0]}, remove_orphans=False, recompute_normals=False)

        self.assertEqual(1, delete_result.removed_face_count)
        self.assertEqual(0, delete_result.removed_vertex_count)
        self.assertEqual(4, len(sm.vertices))
        self.assertEqual([(1, 3, 2)], sm.faces)
        self.assertEqual([10, 11, 12, 13], sm.source_vertex_map)

        compact_result = compact_orphan_vertices(mesh, submesh_indices=(0,), recompute_normals=True)

        self.assertEqual(1, compact_result.removed_vertex_count)
        self.assertEqual((0,), compact_result.affected_submesh_indices)
        self.assertEqual([(1.0, 0.0, 0.0), (-1.0, 1.0, 0.0), (1.0, 1.0, 0.0)], sm.vertices)
        self.assertEqual([(0, 2, 1)], sm.faces)
        self.assertEqual([11, 12, 13], sm.source_vertex_map)
        self.assertEqual(3, len(sm.normals))

    def test_compact_orphans_can_empty_live_deleted_submesh(self) -> None:
        sm = _submesh()
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        delete_faces_touching_vertices(mesh, {0: [0, 1, 2, 3]}, remove_orphans=False, recompute_normals=False)
        compact_result = compact_orphan_vertices(mesh, submesh_indices=(0,))

        self.assertEqual(4, compact_result.removed_vertex_count)
        self.assertEqual((0,), compact_result.emptied_submesh_indices)
        self.assertEqual([], sm.vertices)
        self.assertEqual([], sm.faces)
        self.assertEqual(0, mesh.total_vertices)
        self.assertEqual(0, mesh.total_faces)

    def test_repeated_cloak_shortening_deletes_rows_and_remaps_faces(self) -> None:
        sm = _strip_submesh(rows=6)
        mesh = ParsedMesh(format="obj", submeshes=[sm])
        removed_faces = 0

        for _step in range(6):
            self.assertTrue(sm.faces)
            min_y = min(vertex[1] for vertex in sm.vertices)
            selected = [index for index, vertex in enumerate(sm.vertices) if vertex[1] == min_y]
            result = delete_faces_touching_vertices(mesh, {0: selected})
            removed_faces += int(result.removed_face_count)

            self.assertGreater(result.removed_face_count, 0)
            self.assertEqual(len(sm.vertices), sm.vertex_count)
            self.assertEqual(len(sm.faces), sm.face_count)
            for face in sm.faces:
                self.assertTrue(all(0 <= index < len(sm.vertices) for index in face))

        self.assertEqual(12, removed_faces)
        self.assertEqual([], sm.vertices)
        self.assertEqual([], sm.faces)
        self.assertEqual(0, mesh.total_vertices)
        self.assertEqual(0, mesh.total_faces)


if __name__ == "__main__":
    unittest.main()
