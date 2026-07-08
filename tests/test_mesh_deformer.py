import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.modding.mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    assert_mesh_topology_unchanged,
    build_vertex_adjacency,
    build_x_mirror_pairs,
    clone_mesh_for_editing,
    compact_orphan_vertices,
    delete_faces_by_indices,
    delete_faces_touching_vertices,
    mesh_topology_signature,
    recompute_submesh_normals,
    subdivide_faces_touching_vertices,
)
from cdmw.modding.mesh_exporter import export_obj, write_roundtrip_manifest
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


def _export_mesh() -> ParsedMesh:
    vertex_count = 3
    submesh = SubMesh(
        name="part",
        material="part",
        vertices=[(float(index), 0.0, 0.0) for index in range(vertex_count)],
        uvs=[(0.0, 0.0)] * vertex_count,
        normals=[(0.0, 0.0, 1.0)] * vertex_count,
        faces=[(0, 1, 2)],
        vertex_count=vertex_count,
        face_count=1,
    )
    return ParsedMesh(path="character/model/part.pac", format="pac", submeshes=[submesh], total_vertices=vertex_count, total_faces=1, has_uvs=True)


class MeshDeformerTests(unittest.TestCase):
    def test_clone_mesh_for_editing_preserves_material_route_metadata(self) -> None:
        source = _submesh()
        source.cdmw_material_authority_profile = "material_authority_detail_mask"
        source.cdmw_material_authority_contract = "true_source_authority_detail_mask"
        source.cdmw_source_material_name = "source_mat"
        source.cdmw_target_material_slot_index = 3
        source.cdmw_source_texture_set_key = "source_mat"
        source.preview_native_material_overrides = {"roughness": 0.35, "metalness": 0.8}
        mesh = ParsedMesh(format="obj", submeshes=[source])

        clone = clone_mesh_for_editing(mesh)
        cloned_submesh = clone.submeshes[0]

        self.assertEqual("material_authority_detail_mask", cloned_submesh.cdmw_material_authority_profile)
        self.assertEqual("true_source_authority_detail_mask", cloned_submesh.cdmw_material_authority_contract)
        self.assertEqual("source_mat", cloned_submesh.cdmw_source_material_name)
        self.assertEqual(3, cloned_submesh.cdmw_target_material_slot_index)
        self.assertEqual("source_mat", cloned_submesh.cdmw_source_texture_set_key)
        self.assertEqual({"roughness": 0.35, "metalness": 0.8}, cloned_submesh.preview_native_material_overrides)
        self.assertIsNot(source.preview_native_material_overrides, cloned_submesh.preview_native_material_overrides)

    def test_topology_helpers_ignore_overflow_indices_and_faces(self) -> None:
        source = _submesh()
        source.faces = [(0, float("inf"), 2), (0, 1, 2), (1, 3, 2)]  # type: ignore[list-item]

        signature = mesh_topology_signature(ParsedMesh(format="obj", submeshes=[source]))
        self.assertEqual((3,), signature.face_counts)
        self.assertEqual((((0, 1, 2), (1, 3, 2)),), signature.faces)

        adjacency = build_vertex_adjacency(source)
        self.assertEqual({1, 2}, adjacency[0])
        self.assertEqual({0, 2, 3}, adjacency[1])

        delete_mesh = ParsedMesh(format="obj", submeshes=[copy.deepcopy(source)])
        deleted = delete_faces_by_indices(
            delete_mesh,
            {float("inf"): (0,), 0: (float("inf"), 1)},  # type: ignore[dict-item]
            remove_orphans=False,
            recompute_normals=False,
        )
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(1, deleted.removed_face_count)
        self.assertEqual([(1, 3, 2)], delete_mesh.submeshes[0].faces)

        compacted = copy.deepcopy(source)
        compacted.faces = [(0, float("inf"), 2), (0, 1, 2)]  # type: ignore[list-item]
        compact = compact_orphan_vertices(compacted, recompute_normals=False)
        self.assertEqual((0,), compact.affected_submesh_indices)
        self.assertEqual(1, compact.removed_vertex_count)
        self.assertEqual([(0, 1, 2)], compacted.faces)

        subdivide_mesh = ParsedMesh(format="obj", submeshes=[copy.deepcopy(source)])
        subdivided = subdivide_faces_touching_vertices(
            subdivide_mesh,
            selected_faces_by_submesh={0: (float("inf"), 1)},
            max_faces_per_submesh=float("inf"),  # type: ignore[arg-type]
            recompute_normals=False,
        )
        self.assertEqual((0,), subdivided.affected_submesh_indices)
        self.assertEqual(3, subdivided.added_vertex_count)

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

    def test_delete_faces_by_indices_removes_only_requested_shared_vertex_face(self) -> None:
        sm = _submesh()
        sm.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        sm.normals = [(0.0, 0.0, 1.0)] * 4
        sm.bone_indices = [(0,), (1,), (2,), (3,)]
        sm.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        sm.source_vertex_map = [10, 11, 12, 13]
        sm.source_vertex_offsets = [100, 110, 120, 130]
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        result = delete_faces_by_indices(mesh, {0: [0]})

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

    def test_delete_faces_by_indices_can_defer_orphan_compaction(self) -> None:
        sm = _submesh()
        sm.source_vertex_map = [10, 11, 12, 13]
        mesh = ParsedMesh(format="obj", submeshes=[sm])

        result = delete_faces_by_indices(mesh, {0: [0]}, remove_orphans=False, recompute_normals=False)

        self.assertEqual(1, result.removed_face_count)
        self.assertEqual(0, result.removed_vertex_count)
        self.assertEqual(4, len(sm.vertices))
        self.assertEqual([(1, 3, 2)], sm.faces)
        self.assertEqual([10, 11, 12, 13], sm.source_vertex_map)

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

    def test_export_obj_uses_native_writer_before_python_geometry_loop(self) -> None:
        mesh = ParsedMesh(path="character/model/native.pac", format="pac", submeshes=[_submesh()], total_vertices=4, total_faces=2)

        def fake_native(_mesh, obj_path, _mtl_path, _base, _scale, *, manifest_path="", **_kwargs):
            Path(obj_path).write_text("# native obj\n", encoding="utf-8")
            Path(manifest_path).write_text(
                json.dumps({"format": "mesh_roundtrip_manifest_v2", "submeshes": []}),
                encoding="utf-8",
            )
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("cdmw.modding.mesh_exporter._export_obj_native", side_effect=fake_native) as native:
                exported_paths = export_obj(mesh, temp_dir, "native_route")

            obj_path = Path(exported_paths[0])
            mtl_path = Path(exported_paths[1])
            sidecar_path = Path(exported_paths[2])

            self.assertEqual("# native obj\n", obj_path.read_text(encoding="utf-8"))
            self.assertTrue(mtl_path.is_file())
            self.assertTrue(sidecar_path.is_file())
            self.assertEqual("mesh_roundtrip_manifest_v2", json.loads(sidecar_path.read_text(encoding="utf-8"))["format"])
            native.assert_called_once()

    def test_export_obj_python_fallback_keeps_roundtrip_float_precision(self) -> None:
        submesh = SubMesh(
            name="precise",
            material="precise",
            vertices=[(0.12345678901234567, -0.9876543210987654, 1.0)],
            uvs=[(0.3333333333333333, 0.9876543210987654)],
            normals=[(0.5773502691896258, -0.5773502691896258, 0.5773502691896258)],
            faces=[(0, 0, 0)],
        )
        mesh = ParsedMesh(path="character/model/precise.pac", format="pac", submeshes=[submesh], total_vertices=1, total_faces=1)

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                mock.patch("cdmw.modding.mesh_exporter._export_obj_native", return_value=False),
                mock.patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            ):
                obj_path = Path(export_obj(mesh, temp_dir, "precise")[0])

            obj_text = obj_path.read_text(encoding="utf-8")

        self.assertIn(format(submesh.vertices[0][0], ".17g"), obj_text)
        self.assertIn(format(1.0 - submesh.uvs[0][1], ".17g"), obj_text)
        self.assertIn(format(submesh.normals[0][0], ".17g"), obj_text)
        self.assertNotIn("0.123457", obj_text)

    def test_obj_export_blocks_python_fallback_when_native_available(self) -> None:
        from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

        clear_native_mesh_core_fallback_counts()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                    mock.patch("cdmw.modding.mesh_exporter._export_obj_native", return_value=False),
                    mock.patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                ):
                    with self.assertRaisesRegex(RuntimeError, "Python export fallback was blocked"):
                        export_obj(_export_mesh(), temp_dir, "native_failed")
            self.assertEqual(1, native_mesh_core_fallback_counts()["export.obj.blocked"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_write_roundtrip_manifest_uses_native_writer_before_python_payload_loop(self) -> None:
        mesh = ParsedMesh(path="character/model/native.pac", format="pac", submeshes=[_submesh()], total_vertices=4, total_faces=2)

        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "native_route.obj"
            sidecar_path = Path(f"{obj_path}.meta.json")

            def fake_native(_mesh, _export_path, **_kwargs):
                sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
                return True

            with mock.patch("cdmw.modding.mesh_native_core.write_native_obj_roundtrip_manifest", side_effect=fake_native) as native, mock.patch(
                "cdmw.modding.mesh_exporter._build_roundtrip_manifest_payload",
                side_effect=AssertionError("Python round-trip manifest payload loop should stay fallback-only"),
            ):
                result = write_roundtrip_manifest(mesh, obj_path, companion_path=Path(temp_dir) / "native_route.mtl")

        self.assertEqual(sidecar_path, result)
        native.assert_called_once()

    def test_write_roundtrip_manifest_marks_empty_bone_rows_unweighted(self) -> None:
        weighted = _submesh()
        weighted.name = "weighted"
        weighted.bone_indices = [(0,), (0,), (0,), (0,)]
        weighted.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        unweighted = _submesh()
        unweighted.name = "empty_rows"
        unweighted.bone_indices = [(), (), (), ()]
        unweighted.bone_weights = [(), (), (), ()]
        mesh = ParsedMesh(
            path="character/model/mixed_skinning.pac",
            format="pac",
            submeshes=[unweighted, weighted],
            total_vertices=8,
            total_faces=4,
            has_bones=True,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "mixed_skinning.obj"
            with mock.patch("cdmw.modding.mesh_native_core.write_native_obj_roundtrip_manifest", return_value=False):
                sidecar_path = write_roundtrip_manifest(mesh, obj_path)
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

        first_layout = payload["lods"][0]["submeshes"][0]["bone_layout"]
        second_layout = payload["lods"][0]["submeshes"][1]["bone_layout"]
        self.assertFalse(first_layout["has_bones"])
        self.assertEqual(0, first_layout["max_influences"])
        self.assertTrue(second_layout["has_bones"])
        self.assertEqual(1, second_layout["max_influences"])

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
