from pathlib import Path
import tempfile
import unittest

from cdmw.core.archive_modding import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.final_package_preview import (
    FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC,
    FINAL_PREVIEW_BINDING_GENERATED,
    FINAL_PREVIEW_BINDING_ORIGINAL,
    FINAL_PREVIEW_MISSING_DDS,
    FINAL_PREVIEW_READY,
    FINAL_PREVIEW_SUPPORT_MAPS_ONLY,
    MATERIAL_PREFLIGHT_OVERRIDE_WARNING,
    TEXTURE_PLAN_STATUS_LIKELY_GREY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    apply_material_preflight_override,
    build_dds_override_table_row,
    build_final_package_preview,
    build_replacement_texture_plan_rows,
    material_preflight_hard_blockers,
    simplified_part_label,
    texture_plan_control_description,
)
from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.models import ArchiveModelTextureReference, ModelPreviewData, ModelPreviewMesh
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.static_mesh_replacer import StaticOutputDrawSection


def _preview(material_name: str = "Blade", texture_path: str = "source_preview.png") -> MeshImportPreviewResult:
    mesh = ModelPreviewMesh(
        material_name=material_name,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        indices=[0, 1, 2],
        preview_texture_path=texture_path,
    )
    return MeshImportPreviewResult(
        rebuilt_data=b"not a parsed mesh in this focused test",
        parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
        preview_model=ModelPreviewData(path="character/model/test_weapon.pac", meshes=[mesh]),
        summary_lines=[],
    )


def _sidecar(texture_path: str, parameter: str = "_overlayColorTexture", material: str = "Blade") -> bytes:
    return (
        f'<Root><SkinnedMeshMaterialWrapper _subMeshName="{material}">'
        f'<MaterialParameterTexture _name="{parameter}">'
        f'<ResourceReferencePath_ITexture _path="{texture_path}"/>'
        f"</MaterialParameterTexture>"
        f"</SkinnedMeshMaterialWrapper></Root>"
    ).encode("utf-8")


class FinalPackagePreviewTests(unittest.TestCase):
    def test_generated_sidecar_resolves_generated_dds_and_binds_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview()
            original_texture_name = preview.preview_model.meshes[0].texture_name
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS generated",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_base.dds"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual([], result.likely_grey_materials)
            self.assertEqual(FINAL_PREVIEW_READY, result.binding_rows[0].status)
            self.assertEqual(FINAL_PREVIEW_BINDING_GENERATED, result.binding_rows[0].binding_source)
            self.assertIn("blade_base", result.preview_model.meshes[0].preview_texture_path)
            self.assertNotEqual("source_preview.png", result.preview_model.meshes[0].preview_texture_path)
            self.assertEqual(original_texture_name, result.preview_model.meshes[0].texture_name)
            self.assertTrue(any(line.startswith("Texture Contract:") for line in result.summary_lines))

    def test_final_preview_keeps_slot_identity_for_later_support_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="CD_PHM_02_Handle_0015",
                            texture_name="cd_phm_02_sword_handle_0015",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="cd_phm_02_sword_handle_0015">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_mg.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "gem_base.dds", target_path="character/texture/gem_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "gem_n.dds", target_path="character/texture/gem_n.dds", kind="texture_generated", payload_data=b"DDS normal"),
                MeshImportSupplementalFileSpec(source_path=root / "gem_ma.dds", target_path="character/texture/gem_ma.dds", kind="texture_generated", payload_data=b"DDS material"),
                MeshImportSupplementalFileSpec(source_path=root / "gem_mg.dds", target_path="character/texture/gem_mg.dds", kind="texture_generated", payload_data=b"DDS detail"),
                MeshImportSupplementalFileSpec(source_path=root / "test_weapon.pac_xml", target_path="character/modelproperty/test_weapon.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual([], result.likely_grey_materials)
            self.assertEqual("cd_phm_02_sword_handle_0015", result.preview_model.meshes[0].texture_name)
            self.assertIn("gem_base", result.preview_model.meshes[0].preview_texture_path)
            self.assertIn("gem_n", result.preview_model.meshes[0].preview_normal_texture_path)
            self.assertIn("gem_ma", result.preview_model.meshes[0].preview_material_texture_path)
            self.assertNotIn("gem_mg", result.preview_model.meshes[0].preview_material_texture_path)

    def test_emissive_binding_does_not_override_base_preview_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="Gem")
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Gem">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_emissiveIntensityTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_emi.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "gem_base.dds", target_path="character/texture/gem_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "gem_emi.dds", target_path="character/texture/gem_emi.dds", kind="texture_generated", payload_data=b"DDS emissive"),
                MeshImportSupplementalFileSpec(source_path=root / "gem.pac_xml", target_path="character/modelproperty/gem.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertIn("gem_base", result.preview_model.meshes[0].preview_texture_path)
            self.assertNotIn("gem_emi", result.preview_model.meshes[0].preview_texture_path)

    def test_texture_contract_warns_for_normal_bound_to_color_path_and_orphan_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="Helmet")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet_n.dds",
                    target_path="character/texture/cd_phm_00_hel_0013_05_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "unused.dds",
                    target_path="character/texture/cd_phm_00_hel_0013_05_unused.dds",
                    kind="texture_generated",
                    payload_data=b"DDS unused",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet.pac_xml",
                    target_path="character/modelproperty/helmet.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/cd_phm_00_hel_0013_05.dds", "_normalTexture", "Helmet"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            warning_text = "\n".join(result.warnings)
            self.assertIn("_normalTexture points at a non-normal-looking DDS path", warning_text)
            self.assertIn("generated/copied DDS payloads not referenced", warning_text)
            self.assertIn("cd_phm_00_hel_0013_05_n.dds", warning_text)

    def test_texture_contract_warns_for_stock_shared_generated_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="Helmet")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blackoil.dds",
                    target_path="character/texture/blackoil.dds",
                    kind="texture_generated",
                    payload_data=b"DDS stock",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet.pac_xml",
                    target_path="character/modelproperty/helmet.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blackoil.dds", "_baseColorTexture", "Helmet"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertTrue(any("overrides stock/shared shader texture" in warning for warning in result.warnings))
            self.assertTrue(any("grime/speckles" in warning for warning in result.warnings))

    def test_static_texture_routing_blocker_is_visible_in_final_preview_warnings(self) -> None:
        preview = _preview(material_name="Helmet")
        preview.summary_lines.append(
            "  Texture routing blocker: Helmet receives multiple replacement material sets (Helmet, Horns)."
        )

        result = build_final_package_preview(preview, supplemental_file_specs=())

        warning_text = "\n".join(result.warnings)
        self.assertIn("Texture routing blocker", warning_text)
        self.assertIn("separate source textures cannot be shown on one merged target slot", warning_text)
        self.assertIn("bake/atlas", warning_text)

    def test_final_preview_warns_when_source_preview_has_more_visible_texture_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/helmet.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/helmet.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Helmet",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                            preview_texture_path="source/helmet.png",
                        ),
                        ModelPreviewMesh(
                            material_name="Horns",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                            preview_texture_path="source/horns.png",
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet.dds",
                    target_path="character/texture/helmet.dds",
                    kind="texture_generated",
                    payload_data=b"DDS helmet",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet.pac_xml",
                    target_path="character/modelproperty/helmet.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/helmet.dds", material="Helmet"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            warning_text = "\n".join(result.warnings)
            self.assertIn("fewer visible texture set(s)", warning_text)
            self.assertIn("1/2", warning_text)
            self.assertIn("bake/atlas", warning_text)

    def test_texture_contract_warns_when_base_slot_uses_normal_source_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="Helmet")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "UV_Samurai_Helmet_normal.png",
                    target_path="character/texture/cd_phm_00_hel_0187_01_01_01.dds",
                    kind="texture_generated",
                    payload_data=b"DDS normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "helmet.pac_xml",
                    target_path="character/modelproperty/helmet.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar(
                        "character/texture/cd_phm_00_hel_0187_01_01_01.dds",
                        "_overlayColorTexture",
                        "Helmet",
                    ),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            warning_text = "\n".join(result.warnings)
            self.assertIn("base/overlay color slot", warning_text)
            self.assertIn("normal-map source", warning_text)

    def test_generated_dds_exact_path_wins_over_original_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = root / "original_blade.dds"
            original.write_bytes(b"DDS original")
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "generated.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS generated",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_base.dds"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda _path: original,
            )

            self.assertEqual(FINAL_PREVIEW_READY, result.binding_rows[0].status)
            self.assertEqual(FINAL_PREVIEW_BINDING_GENERATED, result.binding_rows[0].binding_source)
            self.assertIn("blade_base", result.preview_model.meshes[0].preview_texture_path)

    def test_complete_source_owned_warns_draw_order_fallback_with_material_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="CD_PHM_02_Handle_0015",
                            texture_name="CD_PHM_02_Handle_0015",
                            positions=[],
                            indices=[],
                            preview_texture_path="gem_inside_source.png",
                        ),
                        ModelPreviewMesh(
                            material_name="CD_PHM_02_Handle_0015",
                            texture_name="CD_PHM_02_Handle_0015",
                            positions=[],
                            indices=[],
                            preview_texture_path="gem_outside_source.png",
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_outside.dds",
                    target_path="character/texture/gem_outside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem outside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<Root>'
                        b'<SkinnedMeshMaterialWrapper _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper _subMeshName="Gem_outside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_outside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</SkinnedMeshMaterialWrapper>'
                        b'</Root>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("draw-order fallback", warning_text)
            self.assertIn("Gem_inside -> CD_PHM_02_Handle_0015", warning_text)
            self.assertIn("Gem_outside -> CD_PHM_02_Handle_0015", warning_text)

    def test_complete_source_owned_passes_with_exact_cloned_material_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Gem_inside",
                            texture_name="Gem_inside",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Gem_outside",
                            texture_name="Gem_outside",
                            positions=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_outside.dds",
                    target_path="character/texture/gem_outside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem outside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<Root>'
                        b'<SkinnedMeshMaterialWrapper _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper _subMeshName="Gem_outside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_outside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</SkinnedMeshMaterialWrapper>'
                        b'</Root>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            self.assertFalse(result.preflight_errors)
            self.assertFalse(any("draw-order fallback" in warning for warning in result.warnings))
            self.assertEqual([], result.likely_grey_materials)

    def test_complete_source_owned_passes_frostmourne_style_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Blade",
                            texture_name="Blade",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Handle",
                            texture_name="Handle",
                            positions=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Skull",
                            texture_name="Skull",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = []
            wrappers = []
            for item_id, material in enumerate(("Blade", "Handle", "Skull"), start=1337):
                texture_path = f"character/texture/frostmourne_{material.lower()}_base.dds"
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=root / f"{material.lower()}_base.dds",
                        target_path=texture_path,
                        kind="texture_generated",
                        payload_data=f"DDS {material}".encode("ascii"),
                    )
                )
                wrappers.append(
                    f'<SkinnedMeshMaterialWrapper ItemID="{item_id}" _subMeshName="{material}">'
                    f'<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">'
                    f'<Vector Name="_parameters"><MaterialParameterTexture _name="_overlayColorTexture">'
                    f'<ResourceReferencePath_ITexture _path="{texture_path}"/>'
                    f'</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>'
                )
            specs.append(
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        '<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        '<Vector Name="_subMeshResources" IdBase="1339">'
                        + "".join(wrappers)
                        + '</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ).encode("utf-8"),
                )
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=tuple(specs),
                require_source_owned_colors=True,
            )

            self.assertFalse(result.preflight_errors)
            self.assertEqual(3, len(result.binding_rows))
            self.assertEqual([], result.likely_grey_materials)

    def test_complete_source_owned_blocks_pac_xml_wrapper_emitted_outside_submesh_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Gem_inside")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_n.dds",
                    target_path="character/texture/gem_inside_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_ma.dds",
                    target_path="character/texture/gem_inside_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_mg.dds",
                    target_path="character/texture/gem_inside_mg.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside detail",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1189" _subMeshName="Donor"/>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty>'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</SkinnedMeshMaterialWrapper></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("Gem_inside wrapper was emitted outside _subMeshResources", blocker_text)

    def test_complete_source_owned_blocks_duplicate_pac_xml_wrapper_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Gem_inside",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Gem_outside",
                            positions=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_outside.dds",
                    target_path="character/texture/gem_outside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem outside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_normalTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_n.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_ma.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_detailMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_mg.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_outside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_outside.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("Gem_outside duplicates SkinnedMeshMaterialWrapper ItemID 1190 with Gem_inside", blocker_text)

    def test_complete_source_owned_blocks_stale_pac_xml_submesh_resource_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Gem_inside")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_n.dds",
                    target_path="character/texture/gem_inside_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_ma.dds",
                    target_path="character/texture/gem_inside_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_mg.dds",
                    target_path="character/texture/gem_inside_mg.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside detail",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_normalTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_n.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_ma.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_detailMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_mg.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="CD_PHM_02_Handle_0015"/>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("stale original _subMeshResources wrapper", blocker_text)
            self.assertIn("CD_PHM_02_Handle_0015", blocker_text)

    def test_complete_source_owned_allows_planned_runtime_placeholder_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Gem_inside")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Gem_inside", [0], 0, 0, "CD_PHM_02_Handle_0015", 3, True),
                StaticOutputDrawSection(1, 1, "CD_PHM_02_Guard_0015", [], 1, 1, "CD_PHM_02_Guard_0015", 0, False),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_n.dds",
                    target_path="character/texture/gem_inside_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_ma.dds",
                    target_path="character/texture/gem_inside_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_mg.dds",
                    target_path="character/texture/gem_inside_mg.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside detail",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_normalTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_n.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_ma.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_detailMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_mg.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="CD_PHM_02_Guard_0015">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/original_guard.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertNotIn("stale original _subMeshResources wrapper", blocker_text)
            self.assertFalse(result.preflight_errors)

    def test_complete_source_owned_contract_uses_actual_runtime_wrapper_not_all_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_name = "cd_phm_02_sword_handle_0015"
            preview = _preview(runtime_name)
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(
                    0,
                    0,
                    runtime_name,
                    [2],
                    0,
                    0,
                    "CD_PHM_02_Handle_0015",
                    50,
                    False,
                    runtime_slot_name="CD_PHM_02_Handle_0015",
                    runtime_material_name=runtime_name,
                    source_material_name="Gem_inside",
                ),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "handle_base.dds",
                    target_path="character/texture/handle_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS handle base",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "handle_n.dds",
                    target_path="character/texture/handle_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS handle normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "handle_ma.dds",
                    target_path="character/texture/handle_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS handle material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "handle_mg.dds",
                    target_path="character/texture/handle_mg.dds",
                    kind="texture_generated",
                    payload_data=b"DDS handle detail",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        f'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        f'<Vector Name="_subMeshResources" IdBase="1190">'
                        f'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="{runtime_name}">'
                        f'<MaterialParameterTexture _name="_overlayColorTexture">'
                        f'<ResourceReferencePath_ITexture _path="character/texture/handle_base.dds"/>'
                        f'</MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_normalTexture">'
                        f'<ResourceReferencePath_ITexture _path="character/texture/handle_n.dds"/>'
                        f'</MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        f'<ResourceReferencePath_ITexture _path="character/texture/handle_ma.dds"/>'
                        f'</MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_detailMaskTexture">'
                        f'<ResourceReferencePath_ITexture _path="character/texture/handle_mg.dds"/>'
                        f'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        f'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ).encode("utf-8"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertNotIn("Gem_inside", blocker_text)
            self.assertFalse(result.preflight_errors)

    def test_complete_source_owned_allows_weapon_wrapper_without_native_overlay_when_mask_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_name = "cd_phm_02_sword_handle_0015"
            preview = _preview(runtime_name)
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(
                    0,
                    0,
                    runtime_name,
                    [2],
                    0,
                    0,
                    "CD_PHM_02_Handle_0015",
                    50,
                    False,
                    runtime_slot_name="CD_PHM_02_Handle_0015",
                    runtime_material_name=runtime_name,
                    source_material_name="Gem_inside",
                ),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "handle_ma.dds",
                    target_path="character/texture/handle_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS handle material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        f'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        f'<Vector Name="_subMeshResources" IdBase="1190">'
                        f'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="{runtime_name}">'
                        f'<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">'
                        f'<Vector Name="_parameters">'
                        f'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        f'<ResourceReferencePath_ITexture _path="character/texture/handle_ma.dds"/>'
                        f'</MaterialParameterTexture>'
                        f'</Vector></Material></SkinnedMeshMaterialWrapper>'
                        f'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ).encode("utf-8"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("uses generated CD mask/color-blend data as color authority", warning_text)
            self.assertNotIn("lacks generated Base / Color", "\n".join(result.preflight_errors + result.warnings))

    def test_complete_source_owned_contract_uses_wrapper_rows_when_mesh_uses_original_material_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_name = "cd_phm_02_sword_handle_0015_03"
            preview = MeshImportPreviewResult(
                b"not a parsed mesh in this focused test",
                ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="CD_PHM_02_Handle_0015",
                            texture_name="CD_PHM_02_Sword_Handle_0015_03",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                            preview_texture_path="source_preview.png",
                        ),
                    ],
                ),
                [],
            )
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(
                    0,
                    0,
                    runtime_name,
                    [0],
                    0,
                    0,
                    "CD_PHM_02_Handle_0015",
                    3,
                    False,
                    runtime_slot_name="CD_PHM_02_Handle_0015",
                    runtime_material_name=runtime_name,
                    source_material_name="mango",
                ),
            )
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "handle_base.dds", target_path="character/texture/handle_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "handle_n.dds", target_path="character/texture/handle_n.dds", kind="texture_generated", payload_data=b"DDS normal"),
                MeshImportSupplementalFileSpec(source_path=root / "handle_ma.dds", target_path="character/texture/handle_ma.dds", kind="texture_generated", payload_data=b"DDS material"),
                MeshImportSupplementalFileSpec(source_path=root / "handle_detail_ma.dds", target_path="character/texture/handle_detail_ma.dds", kind="texture_generated", payload_data=b"DDS detail"),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        f'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        f'<Vector Name="_subMeshResources" IdBase="1190">'
                        f'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="{runtime_name}">'
                        f'<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">'
                        f'<Vector Name="_parameters">'
                        f'<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/handle_base.dds"/></MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/handle_n.dds"/></MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/handle_ma.dds"/></MaterialParameterTexture>'
                        f'<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/handle_detail_ma.dds"/></MaterialParameterTexture>'
                        f'</Vector></Material></SkinnedMeshMaterialWrapper>'
                        f'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ).encode("utf-8"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
                strict_source_owned_material_contract=True,
            )

            blocker_text = "\n".join(result.preflight_errors + result.warnings)
            self.assertNotIn("has no parsed texture parameters", blocker_text)
            self.assertNotIn("has no exact generated source-visible color authority binding", blocker_text)
            self.assertNotIn("(Normal", blocker_text)
            self.assertNotIn("Material / Mask", blocker_text)
            self.assertNotIn("Detail Mask", blocker_text)

    def test_complete_source_owned_warns_missing_generated_support_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Gem_inside")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Gem_inside", [0], 0, 0, "CD_PHM_02_Handle_0015", 3, True),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("missing generated optional support binding(s): Gem_inside", warning_text)
            self.assertIn("Normal", warning_text)
            self.assertIn("Material / Mask", warning_text)
            self.assertIn("Detail Mask", warning_text)

    def test_complete_source_owned_warns_original_support_binding_survival(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_normal = root / "original_n.dds"
            original_normal.write_bytes(b"DDS original normal")
            preview = _preview("Gem_inside")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Gem_inside", [0], 0, 0, "CD_PHM_02_Handle_0015", 3, True),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_ma.dds",
                    target_path="character/texture/gem_inside_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside_mg.dds",
                    target_path="character/texture/gem_inside_mg.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside detail",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_normalTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_ma.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture _name="_detailMaskTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside_mg.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_normal if path == "character/texture/original_n.dds" else None,
                require_source_owned_colors=True,
            )

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("inherits original Normal binding", warning_text)
            self.assertIn("character/texture/original_n.dds", warning_text)

    def test_complete_source_owned_blocks_surviving_original_layer_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade_base.dds", target_path="character/texture/blade_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_n.dds", target_path="character/texture/blade_n.dds", kind="texture_generated", payload_data=b"DDS normal"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_ma.dds", target_path="character/texture/blade_ma.dds", kind="texture_generated", payload_data=b"DDS material"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_mg.dds", target_path="character/texture/blade_mg.dds", kind="texture_generated", payload_data=b"DDS detail"),
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs, require_source_owned_colors=True)

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("non-generated original/support material parameter", warning_text)
            self.assertIn("_grimeDiffuseTextureR", warning_text)

    def test_true_source_blocks_resolved_inherited_layer_color_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_layer = root / "cd_texturelayer_003_0101.dds"
            original_layer.write_bytes(b"DDS stock layer")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade_base.dds", target_path="character/texture/blade_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_layer if path == "character/texture/cd_texturelayer_003_0101.dds" else None,
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("inherits visible color from the game archive", blocker_text)
            self.assertIn("_grimeDiffuseTextureR", blocker_text)

    def test_detail_preserve_allows_resolved_inherited_layer_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_layer = root / "cd_texturelayer_003_0101.dds"
            original_layer.write_bytes(b"DDS stock layer")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade_base.dds", target_path="character/texture/blade_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_layer if path == "character/texture/cd_texturelayer_003_0101.dds" else None,
                require_source_owned_colors=True,
                allow_inherited_layer_color_bindings=True,
            )

            self.assertFalse(result.preflight_errors)
            self.assertIn("_grimeDiffuseTextureR", "\n".join(result.warnings))
            self.assertIn("Runtime XML preserve", "\n".join(result.summary_lines))

    def test_runtime_xml_contract_warns_inherited_direct_color_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_base = root / "original_base.dds"
            original_base.write_bytes(b"DDS original base")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_base if path == "character/texture/original_base.dds" else None,
                require_source_owned_colors=True,
                material_authority_contract="runtime_xml_preserve",
            )

            self.assertFalse(result.preflight_errors)
            warning_text = "\n".join(result.warnings)
            self.assertIn("inherits visible color from the game archive", warning_text)
            self.assertIn("no exact generated source-visible color authority", warning_text)
            self.assertIn("Runtime XML preserve", "\n".join(result.summary_lines))

    def test_true_source_contract_blocks_inherited_stock_layer_and_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_layer = root / "cd_texturelayer_003_0101.dds"
            original_height = root / "original_disp.dds"
            original_layer.write_bytes(b"DDS stock layer")
            original_height.write_bytes(b"DDS original height")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade_base.dds", target_path="character/texture/blade_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_layer if path == "character/texture/cd_texturelayer_003_0101.dds" else original_height if path == "character/texture/original_disp.dds" else None,
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("inherits visible color from the game archive", blocker_text)
            self.assertIn("inherits original Height binding", blocker_text)
            self.assertIn("True Source Authority", "\n".join(result.summary_lines))

    def test_material_preflight_override_downgrades_overridable_source_authority_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_layer = root / "cd_texturelayer_003_0101.dds"
            original_layer.write_bytes(b"DDS stock layer")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_layer if path == "character/texture/cd_texturelayer_003_0101.dds" else None,
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            self.assertTrue(result.preflight_errors)
            self.assertEqual((), apply_material_preflight_override(result))
            self.assertFalse(result.preflight_errors)
            warning_text = "\n".join(result.warnings)
            self.assertIn(MATERIAL_PREFLIGHT_OVERRIDE_WARNING, warning_text)
            self.assertIn("Unsafe material preflight override:", warning_text)

    def test_material_preflight_override_keeps_hard_blockers(self) -> None:
        blockers = material_preflight_hard_blockers(
            (
                "Visible color texture is not package-resolved: Blade _baseColorTexture -> character/texture/missing.dds.",
                "Complete source-owned draw slot has no exact generated source-visible color authority binding: Blade.",
            )
        )

        self.assertEqual(1, len(blockers))
        self.assertIn("not package-resolved", blockers[0])

    def test_clean_source_contract_warns_instead_of_blocks_missing_wrapper_rows(self) -> None:
        preview = _preview("Blade")
        preview.source_owned_output_draw_sections = (
            StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
        )

        result = build_final_package_preview(
            preview,
            supplemental_file_specs=(),
            require_source_owned_colors=True,
        )

        self.assertFalse(result.preflight_errors)
        self.assertIn("no exact generated source-visible color authority", "\n".join(result.warnings))

    def test_complete_source_owned_warns_height_when_sidecar_keeps_height_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_height = root / "original_disp.dds"
            original_height.write_bytes(b"DDS original height")
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(source_path=root / "blade_base.dds", target_path="character/texture/blade_base.dds", kind="texture_generated", payload_data=b"DDS base"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_n.dds", target_path="character/texture/blade_n.dds", kind="texture_generated", payload_data=b"DDS normal"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_ma.dds", target_path="character/texture/blade_ma.dds", kind="texture_generated", payload_data=b"DDS material"),
                MeshImportSupplementalFileSpec(source_path=root / "blade_mg.dds", target_path="character/texture/blade_mg.dds", kind="texture_generated", payload_data=b"DDS detail"),
                MeshImportSupplementalFileSpec(source_path=root / "blade.pac_xml", target_path="character/modelproperty/blade.pac_xml", kind="sidecar_generated", payload_data=sidecar),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original_height if path == "character/texture/original_disp.dds" else None,
                require_source_owned_colors=True,
            )

            warning_text = "\n".join(result.warnings)
            self.assertFalse(result.preflight_errors)
            self.assertIn("inherits original Height binding", warning_text)
            self.assertIn("keeps original support texture binding", warning_text)

    def test_complete_source_owned_blocks_source_label_used_as_material_shader_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("lambert1")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "lambert1.dds",
                    target_path="character/texture/lambert1.dds",
                    kind="texture_generated",
                    payload_data=b"DDS lambert1",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="lambert1">'
                        b'<Material Name="_resourceMaterial" _materialName="lambert1">'
                        b'<Vector Name="_parameters">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/lambert1.dds"/>'
                        b'</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("lambert1 material shader name is the source material label", blocker_text)
            self.assertIn("SkinnedMeshStandard_Ver2", blocker_text)

    def test_complete_source_owned_blocks_duplicate_material_parameter_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_base.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS base",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_ma.dds",
                    target_path="character/texture/blade_ma.dds",
                    kind="texture_generated",
                    payload_data=b"DDS material",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1190">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
                        b'<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">'
                        b'<Vector Name="_parameters">'
                        b'<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="0">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'<MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture" Index="1">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/blade_ma.dds"/>'
                        b'</MaterialParameterTexture>'
                        b'</Vector></Material></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("Blade duplicates material parameter ItemID 3936485985222654", blocker_text)
            self.assertIn("_overlayColorTexture", blocker_text)
            self.assertIn("_colorBlendingMaskTexture", blocker_text)

    def test_complete_source_owned_blocks_submesh_resource_idbase_below_wrapper_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("lambert1")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "lambert1.dds",
                    target_path="character/texture/lambert1.dds",
                    kind="texture_generated",
                    payload_data=b"DDS lambert1",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1336">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1339" _subMeshName="lambert1">'
                        b'<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">'
                        b'<Vector Name="_parameters">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/lambert1.dds"/>'
                        b'</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("_subMeshResources IdBase 1336 is lower", blocker_text)
            self.assertIn("ItemID 1339", blocker_text)

    def test_complete_source_owned_blocks_sidecar_wrapper_order_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_weapon.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Gem_inside",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Gem_outside",
                            positions=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_inside.dds",
                    target_path="character/texture/gem_inside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem inside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_outside.dds",
                    target_path="character/texture/gem_outside.dds",
                    kind="texture_generated",
                    payload_data=b"DDS gem outside",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        b'<ModelPropertyList><ModelProperty><SkinnedMeshProperty>'
                        b'<Vector Name="_subMeshResources" IdBase="1191">'
                        b'<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Gem_outside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_outside.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Gem_inside">'
                        b'<MaterialParameterTexture _name="_overlayColorTexture">'
                        b'<ResourceReferencePath_ITexture _path="character/texture/gem_inside.dds"/>'
                        b'</MaterialParameterTexture></SkinnedMeshMaterialWrapper>'
                        b'</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
                    ),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                require_source_owned_colors=True,
            )

            blocker_text = "\n".join(result.preflight_errors)
            self.assertIn("wrapper order does not match rebuilt PAC draw order", blocker_text)
            self.assertIn("PAC: Gem_inside, Gem_outside", blocker_text)
            self.assertIn("sidecar: Gem_outside, Gem_inside", blocker_text)

    def test_original_archive_dds_exact_path_is_ready_without_generated_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = root / "blade_base.dds"
            original.write_bytes(b"DDS original")
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_base.dds"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda path: original if path == "character/texture/blade_base.dds" else None,
            )

            self.assertEqual(FINAL_PREVIEW_READY, result.binding_rows[0].status)
            self.assertEqual(FINAL_PREVIEW_BINDING_ORIGINAL, result.binding_rows[0].binding_source)
            self.assertEqual([], result.likely_grey_materials)
            self.assertIn("blade_base.dds", result.preview_model.meshes[0].preview_texture_path)

    def test_original_archive_dds_preview_does_not_require_texconv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = root / "blade_base.dds"
            original.write_bytes(b"DDS original")
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_base.dds"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                texconv_path=None,
                original_dds_resolver=lambda path: original if path == "character/texture/blade_base.dds" else None,
            )

            self.assertEqual(FINAL_PREVIEW_READY, result.binding_rows[0].status)
            self.assertEqual(FINAL_PREVIEW_BINDING_ORIGINAL, result.binding_rows[0].binding_source)
            self.assertIn("blade_base.dds", result.preview_model.meshes[0].preview_texture_path)
            self.assertNotIn("could not be decoded", "\n".join(result.warnings))

    def test_replaced_dds_at_kept_original_sidecar_path_binds_from_texture_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="CD_PHW_00_Nude_00_0001")
            preview.texture_references = (
                ArchiveModelTextureReference(
                    reference_name="character/texture/cd_phw_00_nude_00_0001.dds",
                    material_name="CD_PHW_00_Nude_00_0001",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path="character/texture/cd_phw_00_nude_00_0001.dds",
                ),
                ArchiveModelTextureReference(
                    reference_name="character/texture/cd_phw_00_nude_00_0001_n.dds",
                    material_name="CD_PHW_00_Nude_00_0001",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path="character/texture/cd_phw_00_nude_00_0001_n.dds",
                ),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "body.dds",
                    target_path="character/texture/cd_phw_00_nude_00_0001.dds",
                    kind="texture_generated",
                    payload_data=b"DDS body",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "body_n.dds",
                    target_path="character/texture/cd_phw_00_nude_00_0001_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS normal",
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual([], result.likely_grey_materials)
            self.assertEqual(FINAL_PREVIEW_READY, result.material_statuses[0].status)
            self.assertIn("cd_phw_00_nude_00_0001", result.preview_model.meshes[0].preview_texture_path)
            self.assertIn("cd_phw_00_nude_00_0001_n", result.preview_model.meshes[0].preview_normal_texture_path)

    def test_final_preview_matches_character_materials_with_extra_numeric_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(material_name="CD_PHW_00_Nude_00_0001")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "body.dds",
                    target_path="character/texture/cd_phw_00_nude_00_0001.dds",
                    kind="texture_generated",
                    payload_data=b"DDS body",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "body.pac_xml",
                    target_path="character/modelproperty/body.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar(
                        "character/texture/cd_phw_00_nude_00_0001.dds",
                        material="CD_PHW_00_Nude_0001",
                    ),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual([], result.likely_grey_materials)
            self.assertEqual(FINAL_PREVIEW_READY, result.material_statuses[0].status)
            self.assertIn("cd_phw_00_nude_00_0001", result.preview_model.meshes[0].preview_texture_path)

    def test_final_preview_uses_order_fallback_when_material_names_do_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"not a parsed mesh in this focused test",
                parsed_mesh=ParsedMesh(path="character/model/test_character.pac", format="pac"),
                preview_model=ModelPreviewData(
                    path="character/model/test_character.pac",
                    meshes=[
                        ModelPreviewMesh(
                            material_name="Target_Slot_One",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                        ModelPreviewMesh(
                            material_name="Target_Slot_Two",
                            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            indices=[0, 1, 2],
                        ),
                    ],
                ),
                summary_lines=[],
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "source_body.dds",
                    target_path="character/texture/source_body.dds",
                    kind="texture_generated",
                    payload_data=b"DDS source",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "source.pac_xml",
                    target_path="character/modelproperty/source.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar(
                        "character/texture/source_body.dds",
                        material="Completely_Different_Source_Material",
                    ),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertIn("source_body", result.preview_model.meshes[0].preview_texture_path)
            self.assertTrue(any("draw-order fallback" in warning for warning in result.warnings))
            self.assertIn("Target_Slot_One", result.likely_grey_materials)

    def test_basename_fallback_is_diagnostic_not_exact_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = root / "blade_base.dds"
            original.write_bytes(b"DDS original")
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/folder/blade_base.dds"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                original_dds_resolver=lambda _path: None,
                original_dds_basename_resolver=lambda basename: (original,) if basename == "blade_base.dds" else (),
            )

            self.assertEqual(FINAL_PREVIEW_MISSING_DDS, result.binding_rows[0].status)
            self.assertEqual(FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC, result.binding_rows[0].binding_source)
            self.assertEqual("basename", result.binding_rows[0].confidence)
            self.assertIn("Blade", result.likely_grey_materials)

    def test_sidecar_missing_generated_dds_reports_missing_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/missing_base.dds"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual(FINAL_PREVIEW_MISSING_DDS, result.binding_rows[0].status)
            self.assertIn("Blade", result.likely_grey_materials)
            self.assertIn("character/texture/missing_base.dds", result.missing_texture_paths)

    def test_normal_and_height_only_reports_likely_grey(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "normal.dds",
                    target_path="character/texture/blade_n.dds",
                    kind="texture_generated",
                    payload_data=b"DDS normal",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "height.dds",
                    target_path="character/texture/blade_h.dds",
                    kind="texture_generated",
                    payload_data=b"DDS height",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=(
                        _sidecar("character/texture/blade_n.dds", "_normalTexture")
                        + _sidecar("character/texture/blade_h.dds", "_heightTexture")
                    ),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertIn("Blade", result.likely_grey_materials)
            self.assertEqual(FINAL_PREVIEW_SUPPORT_MAPS_ONLY, result.material_statuses[0].status)

    def test_material_sidecar_parameter_sets_material_semantics_for_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "mask.dds",
                    target_path="character/texture/blade_mask.dds",
                    kind="texture_generated",
                    payload_data=b"DDS mask",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_mask.dds", "_roughnessTexture"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertEqual("roughness", result.preview_model.meshes[0].preview_material_texture_subtype)
            self.assertIn("roughness", result.preview_model.meshes[0].preview_material_texture_packed_channels)

    def test_generated_sidecar_wins_over_source_preview_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview(texture_path="old/source/preview.png")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "new.dds",
                    target_path="character/texture/new_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS new",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/new_base.dds"),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            self.assertNotIn("old/source/preview.png", result.preview_model.meshes[0].preview_texture_path)
            self.assertIn("new_base", result.preview_model.meshes[0].preview_texture_path)

    def test_custom_compact_paths_resolve_final_texture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview()
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "compact.dds",
                    target_path="character/texture/compact_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS compact",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/folder/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/compact_base.dds"),
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                export_options=ModPackageExportOptions(structure="custom_compact_paths"),
            )

            self.assertEqual("character/texture/compact_base.dds", result.binding_rows[0].resolved_texture_path)
            self.assertEqual("character/test_weapon.pac_xml", result.binding_rows[0].sidecar_path)
            self.assertEqual([], result.likely_grey_materials)


class TexturePlanHelperTests(unittest.TestCase):
    def test_part_label_simplifies_common_weapon_parts(self) -> None:
        self.assertEqual("Handle", simplified_part_label("CD_PHM_01_Dagger_Handle_0078"))
        self.assertEqual("Blade", simplified_part_label("cd_phm_01_dagger_blade_0078"))
        self.assertEqual("Guard", simplified_part_label("CD_PHM_01_Dagger_Guard_0078"))
        self.assertEqual("Part 3", simplified_part_label("CD_PHM_01_0078", fallback_index=3))

    def test_part_label_simplifies_non_weapon_parts(self) -> None:
        cases = {
            "CD_ARMOR_01_Helm_0001": "Helmet",
            "npcBodyUpper_0042": "Body",
            "Monster_Rathalos_Wing_L_0003": "Wing",
            "Creature_TailSpike_A": "Spike",
            "Costume_Gauntlets_R": "Gauntlet",
            "Village_Door_Frame_A": "Door",
            "Forest_TreeBranch_02": "Tree",
        }

        for raw_name, expected in cases.items():
            with self.subTest(raw_name=raw_name):
                self.assertEqual(expected, simplified_part_label(raw_name))

    def test_part_label_avoids_short_substring_false_positive(self) -> None:
        self.assertEqual("Armor", simplified_part_label("ArmorPart"))

    def test_dds_override_base_assignment_is_ready(self) -> None:
        row = build_dds_override_table_row(
            {
                "target_name": "BladeMat",
                "part_display": "Blade",
                "slot_kind": "base",
                "role_label": "Base / Color",
                "parameter_name": "BaseColorTexture",
                "target_path": "character/texture/blade_base.dds",
                "source_path": r"C:\tmp\Blade_BaseColor.png",
                "checked": True,
                "visualized": True,
            }
        )

        self.assertEqual(TEXTURE_PLAN_STATUS_READY, row.status.label)
        self.assertEqual("Blade / BladeMat", row.part_material)
        self.assertEqual("Blade", row.part_label)
        self.assertEqual("BaseColorTexture: blade_base.dds", row.original_slot)

    def test_dds_override_missing_base_is_likely_grey(self) -> None:
        row = build_dds_override_table_row(
            {
                "target_name": "BladeMat",
                "slot_kind": "base",
                "role_label": "Base / Color",
                "target_path": "character/texture/blade_base.dds",
                "checked": False,
                "visualized": True,
            }
        )

        self.assertEqual(TEXTURE_PLAN_STATUS_LIKELY_GREY, row.status.label)
        self.assertEqual("red", row.status.color_key)

    def test_dds_override_normal_and_height_are_support_only(self) -> None:
        for slot_kind in ("normal", "height"):
            row = build_dds_override_table_row(
                {
                    "target_name": "BladeMat",
                    "slot_kind": slot_kind,
                    "target_path": f"character/texture/blade_{slot_kind}.dds",
                    "source_path": f"/tmp/blade_{slot_kind}.png",
                    "checked": True,
                    "visualized": True,
                }
            )

            self.assertEqual(TEXTURE_PLAN_STATUS_SUPPORT_ONLY, row.status.label)

    def test_dds_override_standalone_pbr_maps_need_review(self) -> None:
        for slot_kind in ("metallic", "roughness", "ao"):
            row = build_dds_override_table_row(
                {
                    "target_name": "BladeMat",
                    "slot_kind": slot_kind,
                    "target_path": f"character/texture/blade_{slot_kind}.dds",
                    "source_path": f"/tmp/blade_{slot_kind}.png",
                    "checked": True,
                    "visualized": True,
                }
            )

            self.assertEqual(TEXTURE_PLAN_STATUS_REVIEW, row.status.label)
            self.assertIn("pack", row.controls.lower())

    def test_material_mask_description_mentions_shine_metal_roughness(self) -> None:
        description = texture_plan_control_description("material").lower()

        self.assertIn("shine", description)
        self.assertIn("metal", description)
        self.assertIn("roughness", description)

    def test_standalone_pbr_maps_are_detected_but_not_game_effective(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metallic = root / "Blade_Metallic.png"
            metallic.write_bytes(b"")
            texture_set = ReplacementTextureSet(
                material_name="Blade",
                slots={
                    "metallic": ReplacementTextureSlot("Blade", "metallic", metallic),
                },
            )

            rows = build_replacement_texture_plan_rows({"blade": texture_set})

            pbr_rows = [row for row in rows if row.slot_kind == "metallic"]
            self.assertEqual(1, len(pbr_rows))
            self.assertEqual(TEXTURE_PLAN_STATUS_REVIEW, pbr_rows[0].status.label)
            self.assertFalse(pbr_rows[0].game_effective)
            self.assertIn("pack", pbr_rows[0].controls.lower())

    def test_missing_base_color_creates_red_likely_grey_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            normal = root / "Blade_Normal.png"
            normal.write_bytes(b"")
            texture_set = ReplacementTextureSet(
                material_name="Blade",
                slots={
                    "normal": ReplacementTextureSlot("Blade", "normal", normal),
                },
            )

            rows = build_replacement_texture_plan_rows({"blade": texture_set})

            missing_rows = [row for row in rows if row.source == "Missing"]
            self.assertEqual(1, len(missing_rows))
            self.assertEqual(TEXTURE_PLAN_STATUS_LIKELY_GREY, missing_rows[0].status.label)
            self.assertEqual("red", missing_rows[0].status.color_key)


if __name__ == "__main__":
    unittest.main()
