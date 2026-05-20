import tempfile
import unittest
from pathlib import Path

from cdmw.core.archive_modding import attach_scene_preview_textures, parsed_mesh_to_preview_model
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_importer import (
    SceneImportResult,
    append_scene_import_to_mesh,
    discover_scene_texture_files,
    flatten_scene_import_result_parts,
    group_scene_import_result_parts_by_material,
    import_scene_mesh_with_report,
    reduce_scene_import_result_quality,
)


def _mesh(path: str, submeshes: list[SubMesh]) -> ParsedMesh:
    mesh = ParsedMesh(path=path, format="obj", submeshes=submeshes)
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in submeshes)
    vertices = [vertex for submesh in submeshes for vertex in submesh.vertices]
    if vertices:
        xs, ys, zs = zip(*vertices)
        mesh.bbox_min = (min(xs), min(ys), min(zs))
        mesh.bbox_max = (max(xs), max(ys), max(zs))
    return mesh


class SceneMeshAppendTests(unittest.TestCase):
    def test_append_scene_import_preserves_existing_sources_and_updates_totals(self) -> None:
        base_source = SubMesh(
            name="helmet",
            material="helmet_mat",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        target = _mesh("target.obj", [base_source])
        reset_base = _mesh("target.obj", [SubMesh(**base_source.__dict__)])
        horn = SubMesh(
            name="horn",
            material="horn_mat",
            texture="horn_base_color.png",
            vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "horn_base_color.png"
            texture_path.write_bytes(b"texture")
            source_path = Path(temp_dir) / "horns.obj"
            source_path.write_text("# untouched append source\n", encoding="utf-8")
            before_source_text = source_path.read_text(encoding="utf-8")

            result = append_scene_import_to_mesh(
                target,
                reset_base,
                SceneImportResult(
                    mesh=_mesh(str(source_path), [horn]),
                    discovered_texture_files=(texture_path,),
                ),
                source_path=source_path,
                label_prefix="horns",
            )

            self.assertEqual((1,), result.source_indices)
            self.assertEqual(2, len(target.submeshes))
            self.assertEqual(2, len(reset_base.submeshes))
            self.assertEqual("helmet_mat", target.submeshes[0].material)
            self.assertEqual("horn_mat", target.submeshes[1].material)
            self.assertTrue(target.submeshes[1].name.startswith("horns:"))
            self.assertEqual(6, target.total_vertices)
            self.assertEqual(2, target.total_faces)
            self.assertTrue(target.has_uvs)
            self.assertEqual((0.0, 0.0, 0.0), target.bbox_min)
            self.assertEqual((3.0, 1.0, 0.0), target.bbox_max)
            self.assertIn(texture_path.resolve(), result.texture_files)
            self.assertEqual(before_source_text, source_path.read_text(encoding="utf-8"))

    def test_reduce_scene_import_result_quality_is_session_only(self) -> None:
        source = SubMesh(
            name="dense",
            material="dense_mat",
            vertices=[(float(index), float(index % 7), 0.0) for index in range(120)],
            uvs=[(float(index % 10) / 10.0, float(index % 6) / 6.0) for index in range(120)],
            faces=[(index, index + 1, index + 2) for index in range(0, 117, 3)],
        )
        scene_result = SceneImportResult(mesh=_mesh("dense.obj", [source]))

        reduced_result, report = reduce_scene_import_result_quality(
            scene_result,
            max_faces_per_submesh=10,
            max_vertices_per_submesh=30,
        )

        self.assertLessEqual(len(reduced_result.mesh.submeshes[0].faces), 10)
        self.assertLessEqual(len(reduced_result.mesh.submeshes[0].vertices), 30)
        self.assertEqual(len(reduced_result.mesh.submeshes[0].uvs), len(reduced_result.mesh.submeshes[0].vertices))
        self.assertEqual(120, len(scene_result.mesh.submeshes[0].vertices))
        self.assertEqual(39, len(scene_result.mesh.submeshes[0].faces))
        self.assertEqual(120, report.original_vertices)
        self.assertLess(report.reduced_vertices, report.original_vertices)
        self.assertIn("Session-only mesh quality reduction", reduced_result.diagnostics[-1])

    def test_flatten_scene_import_parts_collapses_to_one_appendable_source(self) -> None:
        shell = SubMesh(
            name="horn_left",
            material="horn_mat",
            texture="horn_base.png",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        tip = SubMesh(
            name="horn_right",
            material="horn_mat",
            texture="horn_base.png",
            vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        scene_result = SceneImportResult(mesh=_mesh("horns.obj", [shell, tip]))
        flattened = flatten_scene_import_result_parts(scene_result, part_name="horns_flat")

        self.assertEqual(1, len(flattened.mesh.submeshes))
        flattened_part = flattened.mesh.submeshes[0]
        self.assertEqual("horns_flat", flattened_part.name)
        self.assertEqual("horn_mat", flattened_part.material)
        self.assertEqual("horn_base.png", flattened_part.texture)
        self.assertEqual(6, len(flattened_part.vertices))
        self.assertEqual([(0, 1, 2), (3, 4, 5)], flattened_part.faces)
        self.assertEqual(6, len(flattened_part.uvs))
        self.assertEqual(6, flattened.mesh.total_vertices)
        self.assertEqual(2, flattened.mesh.total_faces)
        self.assertIn("Flattened 2 imported part(s) into one source part", "\n".join(flattened.diagnostics))

    def test_append_flattened_scene_import_adds_one_part(self) -> None:
        base_source = SubMesh(
            name="helmet",
            material="helmet_mat",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        target = _mesh("target.obj", [base_source])
        reset_base = _mesh("target.obj", [SubMesh(**base_source.__dict__)])
        scene_result = SceneImportResult(
            mesh=_mesh(
                "horns.obj",
                [
                    SubMesh(
                        name="horn_a",
                        material="horn_a",
                        vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
                        faces=[(0, 1, 2)],
                    ),
                    SubMesh(
                        name="horn_b",
                        material="horn_b",
                        vertices=[(4.0, 0.0, 0.0), (5.0, 0.0, 0.0), (4.0, 1.0, 0.0)],
                        faces=[(0, 1, 2)],
                    ),
                ],
            )
        )
        flattened = flatten_scene_import_result_parts(scene_result, part_name="horns")

        result = append_scene_import_to_mesh(
            target,
            reset_base,
            flattened,
            source_path=Path("horns.obj"),
            label_prefix="horns",
        )

        self.assertEqual((1,), result.source_indices)
        self.assertEqual(2, len(target.submeshes))
        self.assertEqual("horns", target.submeshes[1].name)
        self.assertEqual(6, len(target.submeshes[1].vertices))
        self.assertEqual(3, target.total_faces)
        self.assertIn("Appended 1 source part", result.diagnostics[-1])

    def test_group_scene_import_parts_by_material_keeps_one_source_per_material(self) -> None:
        scene_result = SceneImportResult(
            mesh=_mesh(
                "horns.obj",
                [
                    SubMesh(
                        name="left_horn_shell",
                        material="horn_shell",
                        texture="horn_shell_base.png",
                        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                        faces=[(0, 1, 2)],
                    ),
                    SubMesh(
                        name="right_horn_shell",
                        material="horn_shell",
                        texture="horn_shell_base.png",
                        vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
                        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                        faces=[(0, 1, 2)],
                    ),
                    SubMesh(
                        name="metal_ring",
                        material="horn_metal",
                        texture="horn_metal_base.png",
                        vertices=[(4.0, 0.0, 0.0), (5.0, 0.0, 0.0), (4.0, 1.0, 0.0)],
                        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                        faces=[(0, 1, 2)],
                    ),
                ],
            )
        )

        grouped = group_scene_import_result_parts_by_material(scene_result, part_name="horns")

        self.assertEqual(2, len(grouped.mesh.submeshes))
        self.assertEqual("horn_shell", grouped.mesh.submeshes[0].material)
        self.assertEqual("horn_metal", grouped.mesh.submeshes[1].material)
        self.assertEqual(6, len(grouped.mesh.submeshes[0].vertices))
        self.assertEqual(2, len(grouped.mesh.submeshes[0].faces))
        self.assertEqual("horn_shell_base.png", grouped.mesh.submeshes[0].texture)
        self.assertIn("Grouped 3 imported part(s) into 2 material group(s)", "\n".join(grouped.diagnostics))

    def test_obj_import_discovers_nearby_texture_folder_when_mtl_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_dir = root / "textures"
            texture_dir.mkdir()
            texture_path = texture_dir / "defaultMat_Base_Color.png"
            texture_path.write_bytes(b"png")
            obj_path = root / "untitled.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "mtllib untitled.mtl",
                        "o Circle.model",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "usemtl HornMaterial",
                        "f 1/1 2/2 3/3",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(obj_path)

            self.assertEqual("obj", result.mesh.format)
            self.assertIn(texture_path.resolve(), result.discovered_texture_files)
            self.assertEqual("defaultMat_Base_Color.png", result.mesh.submeshes[0].texture)

    def test_obj_mtl_texture_references_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_dir = root / "textures"
            texture_dir.mkdir()
            base_texture = texture_dir / "HornMaterial_Base_Color.png"
            normal_texture = texture_dir / "HornMaterial_n.png"
            base_texture.write_bytes(b"base")
            normal_texture.write_bytes(b"normal")
            obj_path = root / "horns.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "mtllib horns.mtl",
                        "o horns",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "usemtl HornMaterial",
                        "f 1/1 2/2 3/3",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "horns.mtl").write_text(
                "\n".join(
                    [
                        "newmtl HornMaterial",
                        "map_Kd textures/HornMaterial_Base_Color.png",
                        "map_Bump -bm 0.5 textures/HornMaterial_n.png",
                    ]
                ),
                encoding="utf-8",
            )

            discovered = discover_scene_texture_files(obj_path)

            self.assertIn(base_texture.resolve(), discovered)
            self.assertIn(normal_texture.resolve(), discovered)

    def test_obj_texture_discovery_checks_sibling_texture_folder_from_source_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            texture_dir = root / "textures"
            source_dir.mkdir()
            texture_dir.mkdir()
            base_texture = texture_dir / "DragonSlaye_Bake_lambert1_BaseColor.png"
            normal_texture = texture_dir / "DragonSlaye_Bake_lambert1_Normal.png"
            base_texture.write_bytes(b"base")
            normal_texture.write_bytes(b"normal")
            obj_path = source_dir / "DragonSlayer_Substance.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "o blade",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "usemtl lambert1",
                        "f 1/1 2/2 3/3",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(obj_path)
            discovered = discover_scene_texture_files(obj_path, result.mesh)

            self.assertIn(base_texture.resolve(), discovered)
            self.assertIn(normal_texture.resolve(), discovered)

    def test_obj_mtl_suffixless_map_kd_sets_submesh_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_dir = root / "textures"
            texture_dir.mkdir()
            base_texture = texture_dir / "wood.png"
            base_texture.write_bytes(b"base")
            obj_path = root / "panel.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "mtllib panel.mtl",
                        "o panel",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "usemtl WoodMaterial",
                        "f 1/1 2/2 3/3",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "panel.mtl").write_text(
                "\n".join(
                    [
                        "newmtl WoodMaterial",
                        "map_Kd textures/wood.png",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(obj_path)

            self.assertIn(base_texture.resolve(), result.discovered_texture_files)
            self.assertEqual("textures/wood.png", result.mesh.submeshes[0].texture)

    def test_obj_missing_mtl_prefers_unique_base_color_over_support_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_dir = root / "textures"
            texture_dir.mkdir()
            base_texture = texture_dir / "all.001_Base_color.png"
            base_texture.write_bytes(b"base")
            for name in (
                "all.001_Emissive.png",
                "all.001_Metallic.png",
                "all.001_Mixed_AO.png",
                "all.001_Normal_GreenUp.png",
                "all.001_Roughness.png",
            ):
                (texture_dir / name).write_bytes(b"support")
            obj_path = root / "sword.obj"
            obj_path.write_text(
                "\n".join(
                    [
                        "mtllib sword.mtl",
                        "o sword",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "usemtl all.001",
                        "f 1/1 2/2 3/3",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_scene_mesh_with_report(obj_path)

            self.assertIn(base_texture.resolve(), result.discovered_texture_files)
            self.assertEqual("all.001_Base_color.png", result.mesh.submeshes[0].texture)

    def test_attach_scene_preview_textures_keeps_basecolor_when_material_name_contains_rma(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gltf_path = root / "scene.gltf"
            gltf_path.write_text("{}", encoding="utf-8")
            texture_dir = root / "textures"
            texture_dir.mkdir()
            base = texture_dir / "BusterMat_baseColor.png"
            normal = texture_dir / "BusterMat_normal.png"
            material = texture_dir / "BusterMat_metallicRoughness.png"
            for texture_path in (base, normal, material):
                texture_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            parsed = _mesh(
                str(gltf_path),
                [
                    SubMesh(
                        name="Buster",
                        material="BusterMat",
                        texture=str(base),
                        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                        faces=[(0, 1, 2)],
                    )
                ],
            )
            preview_model = parsed_mesh_to_preview_model(parsed)
            assigned = attach_scene_preview_textures(
                preview_model,
                SceneImportResult(mesh=parsed, discovered_texture_files=(base, normal, material)),
                gltf_path,
            )

            self.assertGreaterEqual(assigned, 3)
            preview_mesh = preview_model.meshes[0]
            self.assertEqual(str(base), preview_mesh.preview_texture_path)
            self.assertEqual(str(normal), preview_mesh.preview_normal_texture_path)
            self.assertEqual(str(material), preview_mesh.preview_material_texture_path)


if __name__ == "__main__":
    unittest.main()
