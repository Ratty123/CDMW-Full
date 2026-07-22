from __future__ import annotations

from types import SimpleNamespace
import unittest


from cdmw.core.pbd_cloth import (
    build_cloth_constraints,
    build_cloth_pin_weights,
    build_cloth_preview_data,
    build_cloth_preview_from_sidecars,
    classify_pbd_simulation_kind,
    collect_pbd_sidecar_hints,
    parse_pbd_config_materials,
    parse_pbd_material_settings,
)
from cdmw.models import ClothPreviewBatch, ClothPreviewData, ModelPreviewData, ModelPreviewMesh, PbdMaterialSettings


def _square_positions() -> tuple[tuple[float, float, float], ...]:
    return (
        (-0.5, 0.0, 0.0),
        (0.5, 0.0, 0.0),
        (-0.5, 1.0, 0.0),
        (0.5, 1.0, 0.0),
    )


class PbdClothPreviewTests(unittest.TestCase):
    def test_material_lookup_resolves_sidecar_config_and_material_xml(self) -> None:
        sidecar = """
        <ModelProperty>
            <Part _pbdSimulationMaterialName="Armor_Cloak"
                  _materialName="cloak_mat"
                  _subMeshName="cloth_panel" />
        </ModelProperty>
        """
        config = """
        <PbdConfig>
            <Material Name="Armor_Cloak"
                      Filename="Material/Armor/Cloak.xml"
                      Mode="Cloth"
                      PbdPart="Cloak" />
        </PbdConfig>
        """
        material_xml = """
        <PbdMaterial>
            <Float Name="StretchingStiffness" Value="0.72" />
            <Float Name="BendingStiffness" Value="0.41" />
            <Float Name="Damping" Value="0.33" />
            <Float Name="Gravity" Value="-8.5" />
            <Float Name="WindResponse" Value="0.9" />
            <Int Name="SolverIterationCount" Value="12" />
            <Bool Name="CollisionCheck" Value="true" />
            <Bool Name="IsCloak" Value="true" />
        </PbdMaterial>
        """

        hints = collect_pbd_sidecar_hints((("character/model/test.pac_xml", sidecar),))
        materials = parse_pbd_config_materials(config)
        settings = parse_pbd_material_settings(
            material_xml,
            material_name=materials["armorcloak"].name,
            material_path=materials["armorcloak"].filename,
            config_material=materials["armorcloak"],
        )

        self.assertEqual(1, len(hints))
        self.assertEqual("Armor_Cloak", hints[0].simulation_material_name)
        self.assertEqual("cloth", hints[0].simulation_kind)
        self.assertEqual("Material/Armor/Cloak.xml", materials["armorcloak"].filename)
        self.assertEqual("cloth", settings.simulation_kind)
        self.assertAlmostEqual(0.72, settings.stretching_stiffness)
        self.assertAlmostEqual(0.41, settings.bending_stiffness)
        self.assertAlmostEqual(-8.5, settings.gravity)
        self.assertEqual(12, settings.solver_iterations)
        self.assertTrue(settings.collision_enabled)
        self.assertTrue(settings.is_cloak)

    def test_generates_structural_bend_constraints_and_top_pin_weights(self) -> None:
        positions = _square_positions()
        triangles = ((0, 1, 2), (2, 1, 3))
        settings = PbdMaterialSettings(stretching_stiffness=0.6, bending_stiffness=0.2, is_cloak=True)

        constraints = build_cloth_constraints(positions, triangles, settings)
        pin_weights = build_cloth_pin_weights(positions, cloak_bias=True)

        structural = [constraint for constraint in constraints if constraint.kind == "structural"]
        bend = [constraint for constraint in constraints if constraint.kind == "bend"]
        self.assertEqual(5, len(structural))
        self.assertEqual(1, len(bend))
        self.assertEqual({0.0, 1.0}, set(pin_weights))
        self.assertEqual((0.0, 0.0, 1.0, 1.0), pin_weights)

    def test_pin_weights_anchor_each_detached_hair_island(self) -> None:
        positions = (
            (-0.5, 10.0, 0.0),
            (0.5, 10.0, 0.0),
            (-0.5, 11.0, 0.0),
            (0.5, 11.0, 0.0),
            (-0.5, 0.0, 0.0),
            (0.5, 0.0, 0.0),
            (-0.5, 1.0, 0.0),
            (0.5, 1.0, 0.0),
        )
        triangles = ((0, 1, 2), (2, 1, 3), (4, 5, 6), (6, 5, 7))

        pin_weights = build_cloth_pin_weights(positions, simulation_kind="hair", triangles=triangles)

        self.assertEqual((0.0, 0.0, 1.0, 1.0), pin_weights[:4])
        self.assertEqual((0.0, 0.0, 1.0, 1.0), pin_weights[4:])

    def test_attachment_anchors_pin_horizontal_weapon_flag_near_rigid_mesh(self) -> None:
        positions = (
            (-2.0, 0.0, 0.0),
            (-2.0, 0.4, 0.0),
            (-1.0, 0.0, 0.0),
            (-1.0, 0.4, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.4, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 0.4, 0.0),
        )
        triangles = ((0, 1, 2), (2, 1, 3), (2, 3, 4), (4, 3, 5), (4, 5, 6), (6, 5, 7))

        pin_weights = build_cloth_pin_weights(
            positions,
            simulation_kind="spline",
            triangles=triangles,
            attachment_positions=((0.0, 0.2, 0.0),),
        )

        self.assertGreater(pin_weights[4], 0.0)
        self.assertGreater(pin_weights[5], 0.0)
        self.assertEqual(0.0, pin_weights[0])
        self.assertEqual(0.0, pin_weights[1])

    def test_builds_cloth_preview_data_for_matching_cloth_mesh(self) -> None:
        positions = _square_positions()
        mesh = ModelPreviewMesh(
            material_name="cloak_mat",
            positions=list(positions),
            indices=[0, 1, 2, 2, 1, 3],
            source_submesh_index=0,
        )
        model = ModelPreviewData(path="character/model/test_cloak.pac", meshes=[mesh])
        parsed_mesh = SimpleNamespace(
            submeshes=[
                SimpleNamespace(
                    name="cloth_panel",
                    material="cloak_mat",
                    bone_indices=((1, 2), (1, 2), (3, 4), (3, 4)),
                    bone_weights=((0.75, 0.25), (0.75, 0.25), (0.50, 0.50), (0.50, 0.50)),
                )
            ]
        )
        hints = collect_pbd_sidecar_hints(
            (
                (
                    "character/model/test_cloak.pac_xml",
                    '<ModelProperty><Part _pbdSimulationMaterialName="Armor_Cloak" _materialName="cloak_mat" _subMeshName="cloth_panel" /></ModelProperty>',
                ),
            )
        )
        settings = PbdMaterialSettings(material_name="Armor_Cloak", simulation_kind="cloth", is_cloak=True)

        cloth = build_cloth_preview_data(model, parsed_mesh, hints, {"armorcloak": settings})

        self.assertIsNotNone(cloth)
        assert cloth is not None
        self.assertEqual(1, len(cloth.batches))
        batch = cloth.batches[0]
        self.assertEqual(0, batch.mesh_index)
        self.assertEqual(0, batch.source_submesh_index)
        self.assertEqual("Armor_Cloak", batch.simulation_material_name)
        self.assertEqual(4, len(batch.positions))
        self.assertGreaterEqual(len(batch.constraints), 6)
        self.assertEqual(((1, 2), (1, 2), (3, 4), (3, 4)), batch.bone_indices)
        self.assertIn("not game/Havok exact", " ".join(batch.notes))

    def test_soft_pbd_hair_leather_and_rope_emit_runtime_batches(self) -> None:
        cases = (
            ("LongHair", "hair_mat", "hair_cards", "hair"),
            ("ArmorLeather", "leather_mat", "leather_panel", "leather"),
            ("HangingRope", "rope_mat", "rope_strand", "rope"),
        )
        for pbd_name, material_name, submesh_name, expected_kind in cases:
            with self.subTest(expected_kind=expected_kind):
                positions = _square_positions()
                model = ModelPreviewData(
                    path=f"character/model/test_{expected_kind}.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name=material_name,
                            positions=list(positions),
                            indices=[0, 1, 2, 2, 1, 3],
                            source_submesh_index=0,
                        )
                    ],
                )
                parsed_mesh = SimpleNamespace(submeshes=[SimpleNamespace(name=submesh_name, material=material_name)])
                hints = collect_pbd_sidecar_hints(
                    (
                        f'<ModelProperty><Part _pbdSimulationMaterialName="{pbd_name}" '
                        f'_materialName="{material_name}" _subMeshName="{submesh_name}" /></ModelProperty>',
                    )
                )

                preview = build_cloth_preview_data(model, parsed_mesh, hints, {})

                self.assertIsNotNone(preview)
                assert preview is not None
                self.assertEqual(expected_kind, preview.batches[0].simulation_kind)
                self.assertEqual(expected_kind, preview.batches[0].material_settings.simulation_kind)
                self.assertIn("PBD physics", preview.summary)

    def test_standalone_hkx_does_not_emit_pbd_runtime(self) -> None:
        self.assertIsNone(
            build_cloth_preview_from_sidecars(
                ModelPreviewData(path="character/bin__/meshphysics/body.hkx"),
                SimpleNamespace(submeshes=[]),
                (),
                "",
                lambda _material: ("", ""),
            )
        )

    def test_weapon_spline_pbd_does_not_emit_cloth_runtime(self) -> None:
        positions = _square_positions()
        model = ModelPreviewData(
            path="character/model/weapon/test_sword.pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_PHM_02_Blade_0014",
                    positions=list(positions),
                    indices=[0, 1, 2, 2, 1, 3],
                    source_submesh_index=0,
                )
            ],
        )
        parsed_mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="blade", material="CD_PHM_02_Blade_0014")])
        weapon_hints = collect_pbd_sidecar_hints(
            (
                '<ModelProperty><Part _pbdSimulationMaterialName="WeaponSpline" '
                '_materialName="CD_PHM_02_Blade_0014" _subMeshName="blade" /></ModelProperty>',
            )
        )

        self.assertEqual("spline", classify_pbd_simulation_kind("WeaponSpline"))
        self.assertEqual("spline", weapon_hints[0].simulation_kind)
        self.assertIsNone(build_cloth_preview_data(model, parsed_mesh, weapon_hints, {}))

    def test_vortice_pbd_runtime_tracks_scene_transform_and_reset(self) -> None:
        from pathlib import Path

        source = Path("tools/dotnet_mesh_editor_experiment/D3D11MaterialViewport.PreviewOverlays.cs").read_text(encoding="utf-8")

        self.assertIn("ActivePaneModelMatrix(0) * _camera.WorldViewProjection", source)
        self.assertIn("ResetClothOverlaySimulation(overlays)", source)
        self.assertIn("overlays.ClothResetGeneration", source)
        self.assertIn("overlays.ClothWindStrength", source)

    def test_prepare_model_preview_preserves_cloth_for_source_submesh_zero(self) -> None:
        from cdmw.rendering.model_preview_prepare import prepare_model_preview

        cloth_batch = ClothPreviewBatch(
            mesh_index=-1,
            source_submesh_index=0,
            positions=_square_positions(),
            pin_weights=(0.0, 0.0, 1.0, 1.0),
        )
        model = ModelPreviewData(
            path="character/model/test_cloak.pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="cloak_mat",
                    positions=list(_square_positions()),
                    indices=[0, 1, 2, 2, 1, 3],
                    source_submesh_index=0,
                )
            ],
            cloth_preview=ClothPreviewData(batches=(cloth_batch,)),
        )

        _cloned, prepared = prepare_model_preview(model)

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual(1, len(prepared.batches))
        self.assertIs(prepared.batches[0].cloth_preview, cloth_batch)


if __name__ == "__main__":
    unittest.main()
