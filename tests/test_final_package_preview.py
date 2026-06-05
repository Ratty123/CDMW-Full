import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

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
from cdmw.models import ArchiveModelTextureReference, ModelPreviewData, ModelPreviewMesh, ModelPreviewRenderSettings, PreviewMaterialTextureInput
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


def _dds(
    width: int = 4,
    height: int = 4,
    *,
    mips: int = 3,
    depth: int = 1,
    fourcc: bytes | None = b"DXT1",
    rgba: bool = False,
    bgra: bool = False,
) -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x0002100F)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 20, depth)
    struct.pack_into("<I", header, 24, mips)
    struct.pack_into("<I", header, 72, 32)
    if rgba or bgra:
        struct.pack_into("<I", header, 76, 0x41)
        struct.pack_into("<I", header, 84, 32)
        struct.pack_into("<I", header, 88, 0x00FF0000 if bgra else 0x000000FF)
        struct.pack_into("<I", header, 92, 0x0000FF00)
        struct.pack_into("<I", header, 96, 0x000000FF if bgra else 0x00FF0000)
        struct.pack_into("<I", header, 100, 0xFF000000)
    else:
        struct.pack_into("<I", header, 76, 0x4)
        header[80:84] = fourcc or b"DXT1"
    return b"DDS " + bytes(header) + b"\x00" * 512


def _dds_rgba_pixels(pixels: list[tuple[int, int, int, int]], *, bgra: bool = False) -> bytes:
    width = max(1, len(pixels))
    header = _dds(width=width, height=1, mips=1, rgba=not bgra, bgra=bgra)[:128]
    payload = bytearray()
    for red, green, blue, alpha in pixels or [(0, 0, 0, 255)]:
        if bgra:
            payload.extend((blue, green, red, alpha))
        else:
            payload.extend((red, green, blue, alpha))
    return header + bytes(payload)


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

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                render_settings=ModelPreviewRenderSettings(d3d11_normal_y_mode="force_no_flip"),
            )

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

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                render_settings=ModelPreviewRenderSettings(d3d11_normal_y_mode="force_no_flip"),
            )

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

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                render_settings=ModelPreviewRenderSettings(d3d11_normal_y_mode="force_no_flip"),
            )

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

    def test_material_authority_report_records_source_routing_unknowns_and_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(0, 0, "Blade", [0], 0, 0, "Blade", 1, True),
            )
            original_sidecar_path = root / "blade.pac_xml"
            original_sidecar_path.write_text(
                (
                    '<Root><Vector Name="_subMeshResources" IdBase="1190">'
                    '<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
                    '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture StringItemID="_detailMaskTexture" ItemID="2838988925698046" _name="_detailMaskTexture" Index="1"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                    "</SkinnedMeshMaterialWrapper></Vector></Root>"
                ),
                encoding="utf-8",
            )
            sidecar = (
                '<Root><Vector Name="_subMeshResources" IdBase="1190">'
                '<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_grimeDiffuseTextureR" ItemID="2838988925698047" _name="_grimeDiffuseTextureR" Index="1"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                '<MaterialParameterFloat StringItemID="_wetnessBoost" ItemID="34" _name="_wetnessBoost" _value="0.25" Index="2"/>'
                '<MaterialParameterBool StringItemID="_alphaBlend" ItemID="36" _name="_alphaBlend" _value="1" Index="3"/>'
                "</SkinnedMeshMaterialWrapper></Vector></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_base.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=b"DDS base",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=original_sidecar_path,
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                    note="Generated patched PAC XML for source-authority material.",
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                source_path=root / "source_blade.glb",
                require_source_owned_colors=True,
                material_authority_contract="true_source_authority",
            )

            report = result.material_authority_report.to_dict()
            routing_params = {row["parameter_name"] for row in report["routing"]}
            overlay_route = next(row for row in report["routing"] if row["parameter_name"] == "_overlayColorTexture")
            texture_outputs = {row["target_path"]: row for row in report["texture_outputs"]}
            unknowns = report["unknown_material_response_parameters"]
            flags = set(report["risk_flags"])
            sidecar_report = report["sidecar_reports"][0]
            sidecar_output = report["sidecar_outputs"][0]
            self.assertEqual("cdmw_material_authority_report_v1", report["schema"])
            self.assertTrue(str(report["source_path"]).endswith("source_blade.glb"))
            self.assertEqual("true_source_authority", report["authority_contract"])
            self.assertIn("_overlayColorTexture", routing_params)
            self.assertIn("_grimeDiffuseTextureR", routing_params)
            for route in report["routing"]:
                self.assertTrue(route["material_name"])
                self.assertTrue(route["role"])
                self.assertTrue(route["parameter_name"])
                self.assertTrue(route["status"])
                self.assertTrue(route["binding_source"])
                self.assertTrue(route["confidence"])
            self.assertEqual("ready", overlay_route["status"])
            self.assertEqual("generated", overlay_route["binding_source"])
            self.assertEqual("character/texture/blade_base.dds", overlay_route["resolved_texture_path"])
            self.assertIn("character/texture/blade_base.dds", texture_outputs)
            self.assertEqual(len(b"DDS base"), texture_outputs["character/texture/blade_base.dds"]["bytes"])
            self.assertTrue(texture_outputs["character/texture/blade_base.dds"]["sha256"])
            self.assertEqual("_wetnessBoost", unknowns[0]["parameter_name"])
            self.assertIn("inherited_target_influence", flags)
            self.assertIn("unknown_material_response", flags)
            self.assertIn("missing_final_dds", flags)
            self.assertEqual("character/modelproperty/blade.pac_xml", sidecar_output["target_path"])
            self.assertTrue(sidecar_output["generated"])
            self.assertEqual("sidecar_generated", sidecar_output["kind"])
            self.assertEqual(len(sidecar), sidecar_output["bytes"])
            self.assertTrue(sidecar_output["sha256"])
            edit_summary = sidecar_output["pac_xml_edit_summary"]
            self.assertEqual("source_compared", edit_summary["status"])
            self.assertTrue(edit_summary["changed_from_source"])
            self.assertEqual(2, edit_summary["source_texture_ref_count"])
            self.assertEqual(2, edit_summary["payload_texture_ref_count"])
            self.assertEqual(1, edit_summary["texture_refs_added_count"])
            self.assertEqual(1, edit_summary["texture_refs_removed_count"])
            self.assertEqual(1, edit_summary["texture_refs_changed_count"])
            self.assertEqual(
                {"_detailMaskTexture", "_grimeDiffuseTextureR", "_overlayColorTexture"},
                set(edit_summary["changed_parameter_names"]),
            )
            self.assertEqual("source_compared", edit_summary["structural_compare_status"])
            self.assertTrue(edit_summary["wrapper_order_preserved"])
            self.assertTrue(edit_summary["wrapper_item_ids_preserved"])
            self.assertTrue(edit_summary["submesh_bindings_preserved"])
            self.assertTrue(edit_summary["submesh_item_ids_preserved"])
            self.assertFalse(edit_summary["parameter_abi_preserved"])
            self.assertEqual(1, edit_summary["source_wrapper_order_count"])
            self.assertEqual(1, edit_summary["payload_wrapper_order_count"])
            self.assertEqual(2, edit_summary["source_parameter_abi_count"])
            self.assertEqual(4, edit_summary["payload_parameter_abi_count"])
            self.assertEqual("needs_review", sidecar_output["authority_status"])
            self.assertEqual(1, sidecar_output["wrapper_count"])
            self.assertEqual(1, sidecar_output["submesh_binding_count"])
            self.assertEqual(4, sidecar_output["parameter_count"])
            self.assertEqual(1, sidecar_output["neutralization_action_count"])
            self.assertIn("Generated patched PAC XML", sidecar_output["note"])
            self.assertTrue(sidecar_report["inherited_influence_parameters"])
            self.assertEqual(1, len(sidecar_report["neutralization_actions"]))
            self.assertEqual(
                "replace_with_source_owned_texture_or_neutral_default",
                sidecar_report["neutralization_actions"][0]["action"],
            )
            self.assertTrue(sidecar_report["neutralization_actions"][0]["preserve_runtime_abi"])
            self.assertEqual("Blade", sidecar_report["wrapper_order"][0]["wrapper_name"])
            self.assertEqual("1190", sidecar_report["wrapper_order"][0]["item_id"])
            self.assertEqual(4, sidecar_report["wrapper_order"][0]["parameter_count"])
            self.assertEqual("Blade", sidecar_report["submesh_bindings"][0]["wrapper_name"])
            self.assertEqual("1190", sidecar_report["submesh_bindings"][0]["item_id"])
            self.assertEqual("1190", sidecar_report["submesh_bindings"][0]["id_base"])
            self.assertEqual(4, sidecar_report["submesh_bindings"][0]["parameter_count"])
            self.assertEqual("34", unknowns[0]["item_id"])
            self.assertEqual("2", unknowns[0]["index"])
            scalar_ranges = {row["parameter_name"]: row for row in sidecar_report["scalar_ranges"]}
            self.assertEqual(0.25, scalar_ranges["_wetnessBoost"]["min"])
            self.assertEqual(0.25, scalar_ranges["_wetnessBoost"]["max"])
            alpha_controls = {row["parameter_name"]: row for row in sidecar_report["alpha_controls"]}
            self.assertEqual("alpha_blend", alpha_controls["_alphaBlend"]["mode"])
            self.assertEqual(1.0, alpha_controls["_alphaBlend"]["numeric_value"])
            self.assertTrue(report["target_sections"])
            self.assertIn("Material authority risk flags:", "\n".join(result.summary_lines))

    def test_material_authority_report_validates_dds_payload_channels_and_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_rgba.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_roughnessTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_r.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_emissiveIntensityTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_bad.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_rgba.dds",
                    target_path="character/texture/blade_rgba.dds",
                    kind="texture_generated",
                    payload_data=_dds(rgba=True),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_n.dds",
                    target_path="character/texture/blade_n.dds",
                    kind="texture_generated",
                    payload_data=_dds(fourcc=b"DXT1"),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_ma.dds",
                    target_path="character/texture/blade_ma.dds",
                    kind="texture_generated",
                    payload_data=_dds(fourcc=b"DXT1"),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_r.dds",
                    target_path="character/texture/blade_r.dds",
                    kind="texture_generated",
                    payload_data=_dds(width=8, height=8, mips=1, fourcc=b"DXT1"),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_bad.dds",
                    target_path="character/texture/blade_bad.dds",
                    kind="texture_generated",
                    payload_data=b"not a DDS payload",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(
                preview,
                supplemental_file_specs=specs,
                render_settings=ModelPreviewRenderSettings(d3d11_normal_y_mode="force_no_flip"),
            )

            report = result.material_authority_report.to_dict()
            outputs = {row["target_path"]: row for row in report["texture_outputs"]}
            flags = set(report["risk_flags"])
            rgba_validation = outputs["character/texture/blade_rgba.dds"]["dds_validation"]
            rgba_conversion = outputs["character/texture/blade_rgba.dds"]["conversion_policy"]
            rgba_visualization = outputs["character/texture/blade_rgba.dds"]["channel_visualization"][0]
            normal_visualization = outputs["character/texture/blade_n.dds"]["channel_visualization"][0]
            mask_visualization = outputs["character/texture/blade_ma.dds"]["channel_visualization"][0]
            mask_conversion = outputs["character/texture/blade_ma.dds"]["conversion_policy"]
            normal_diagnostics = {
                row["code"]
                for row in outputs["character/texture/blade_n.dds"]["role_diagnostics"]
            }
            normal_policy = next(
                row
                for row in outputs["character/texture/blade_n.dds"]["role_diagnostics"]
                if row["code"] == "normal_y_policy"
            )
            rough_findings = {
                row["code"]
                for row in outputs["character/texture/blade_r.dds"]["dds_validation"]["findings"]
            }

            self.assertEqual("rgba", rgba_validation["channel_order"])
            self.assertEqual("texture_generated", rgba_conversion["payload_kind"])
            self.assertTrue(rgba_conversion["generated"])
            self.assertTrue(rgba_conversion["inline_payload"])
            self.assertIn("base_color", rgba_conversion["bound_role_classes"])
            self.assertEqual("rgba", rgba_conversion["channel_order"])
            self.assertEqual("visible_color", rgba_visualization["kind"])
            self.assertEqual(["red", "green", "blue", "alpha"], [row["semantic"] for row in rgba_visualization["channels"]])
            self.assertEqual("normal_xy", normal_visualization["kind"])
            self.assertEqual(["normal_x", "normal_y"], [row["semantic"] for row in normal_visualization["channels"]])
            self.assertEqual("packed_material_mask", mask_visualization["kind"])
            self.assertIn("material", mask_conversion["bound_role_classes"])
            self.assertEqual(("packed_material_mask",), tuple(mask_conversion["channel_visualization_kinds"]))
            self.assertEqual(["ao", "roughness", "metallic", "alpha"], [row["semantic"] for row in mask_visualization["channels"]])
            self.assertIn("uncompressed_channel_order", {row["code"] for row in outputs["character/texture/blade_rgba.dds"]["role_diagnostics"]})
            self.assertEqual("BC1_UNORM", outputs["character/texture/blade_n.dds"]["dds_validation"]["texconv_format"])
            self.assertIn("normal_y_policy", normal_diagnostics)
            self.assertIn("normal_y_policy_unconfirmed", normal_diagnostics)
            self.assertIn("normal_y_policy", report["preview_settings"])
            self.assertEqual("force_no_flip", report["preview_settings"]["normal_y_policy"]["d3d11_normal_y_mode"])
            self.assertEqual(1, report["preview_settings"]["source_preview_visible_texture_sets"])
            self.assertGreaterEqual(report["preview_settings"]["final_preview_visible_texture_sets"], 0)
            self.assertEqual(
                report["preview_settings"]["source_preview_visible_texture_sets"]
                - report["preview_settings"]["final_preview_visible_texture_sets"],
                report["preview_settings"]["preview_visible_texture_delta"],
            )
            self.assertEqual("force_no_flip", normal_policy["d3d11_normal_y_mode"])
            self.assertEqual("force_preserve_normal_y", normal_policy["effective_preview_policy"])
            self.assertIn("normal_format_not_bc5", normal_diagnostics)
            self.assertIn("missing_mips", rough_findings)
            self.assertEqual("invalid", outputs["character/texture/blade_bad.dds"]["dds_validation"]["status"])
            self.assertIn("invalid_dds_payload", flags)
            self.assertIn("missing_dds_dimensions", flags)
            self.assertIn("missing_dds_format", flags)
            self.assertIn("missing_dds_mips", flags)
            self.assertIn("normal_format_mismatch", flags)
            self.assertIn("normal_y_policy_unconfirmed", flags)
            self.assertLess(outputs["character/texture/blade_rgba.dds"]["visible_luma_mean"], 45.0)
            self.assertIn("dark_visible_color_output", flags)

    def test_material_authority_report_treats_emissive_intensity_texture_as_control_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Gem")
            sidecar = _sidecar("character/texture/gem_base_red_emi.dds", "_emissiveIntensityTexture", "Gem")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_emi.dds",
                    target_path="character/texture/gem_base_red_emi.dds",
                    kind="texture_generated",
                    payload_data=_dds(fourcc=b"ATI2"),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem.pac_xml",
                    target_path="character/modelproperty/gem.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            output = result.material_authority_report.to_dict()["texture_outputs"][0]
            diagnostic_codes = {row["code"] for row in output["role_diagnostics"]}
            flags = set(result.material_authority_report.to_dict()["risk_flags"])
            self.assertEqual("BC5_UNORM", output["dds_validation"]["texconv_format"])
            self.assertEqual(("emissive_control",), tuple(output["conversion_policy"]["bound_role_classes"]))
            self.assertEqual(("emissive_control",), tuple(output["conversion_policy"]["channel_visualization_kinds"]))
            self.assertEqual("emissive_control", output["channel_visualization"][0]["kind"])
            self.assertNotIn("visible_color_technical_format", diagnostic_codes)
            self.assertNotIn("visible_color_format_mismatch", flags)

    def test_material_authority_report_records_inline_uncompressed_dds_luma(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            sidecar = _sidecar("character/texture/blade_base.dds", "_overlayColorTexture", "Blade")
            payload = _dds_rgba_pixels([(10, 20, 30, 255), (110, 120, 130, 255)])
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_base.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=payload,
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            output = result.material_authority_report.to_dict()["texture_outputs"][0]
            expected_luma = (0.2126 * 60.0) + (0.7152 * 70.0) + (0.0722 * 80.0)
            self.assertAlmostEqual(expected_luma, output["visible_luma_mean"], places=4)

    def test_material_authority_report_hashes_file_backed_dds_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            dds_payload = _dds()
            dds_path = root / "blade_base.dds"
            dds_path.write_bytes(dds_payload)
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/>'
                "</MaterialParameterTexture></SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=dds_path,
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=b"",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            output = result.material_authority_report.to_dict()["texture_outputs"][0]
            expected_hash = hashlib.sha256(dds_payload).hexdigest()
            self.assertEqual("source_file", output["payload_source"])
            self.assertEqual(len(dds_payload), output["bytes"])
            self.assertEqual(expected_hash, output["sha256"])
            self.assertEqual(expected_hash, output["output_sha256"])
            self.assertEqual(len(dds_payload), output["source_bytes"])
            self.assertEqual(expected_hash, output["source_sha256"])

    def test_material_authority_report_records_bgra_visible_color_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/blade_bgra.dds"/>'
                "</MaterialParameterTexture></SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_bgra.dds",
                    target_path="character/texture/blade_bgra.dds",
                    kind="texture_generated",
                    payload_data=_dds(bgra=True),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            output = result.material_authority_report.to_dict()["texture_outputs"][0]
            visualization = output["channel_visualization"][0]
            self.assertEqual("B8G8R8A8_UNORM", output["dds_validation"]["texconv_format"])
            self.assertEqual("bgra", output["dds_validation"]["channel_order"])
            self.assertEqual("bgra", output["conversion_policy"]["channel_order"])
            self.assertEqual("visible_color", visualization["kind"])
            self.assertEqual(
                [("B", "red"), ("G", "green"), ("R", "blue"), ("A", "alpha")],
                [(row["channel"], row["semantic"]) for row in visualization["channels"]],
            )

    def test_material_authority_report_records_render_preview_settings(self) -> None:
        preview = _preview("Blade")
        render_settings = ModelPreviewRenderSettings(
            visible_texture_mode="sidecar_visible_first",
            render_diagnostic_mode="source_pbr_preview",
            alpha_handling_mode="show_alpha",
            d3d11_view_mode="game_outdoor",
            d3d11_normal_y_mode="force_no_flip",
            d3d11_roughness_bias=0.25,
            d3d11_metalness_scale=0.9,
            d3d11_emissive_gain=1.7,
            flip_texture_v=True,
            disable_all_support_maps=True,
        )

        result = build_final_package_preview(preview, render_settings=render_settings)

        settings = result.material_authority_report.to_dict()["preview_settings"]
        self.assertEqual("provided", settings["render_settings_source"])
        self.assertEqual(1, settings["source_preview_mesh_parts"])
        self.assertEqual(1, settings["final_preview_mesh_parts"])
        self.assertEqual(1, settings["source_preview_visible_texture_sets"])
        self.assertEqual(0, settings["final_preview_visible_texture_sets"])
        self.assertEqual(1, settings["preview_visible_texture_delta"])
        self.assertEqual("sidecar_visible_first", settings["visible_texture_mode"])
        self.assertEqual("source_pbr_preview", settings["render_diagnostic_mode"])
        self.assertEqual("show_alpha", settings["alpha_handling_mode"])
        self.assertEqual("game_outdoor", settings["d3d11_view_mode"])
        self.assertEqual("force_no_flip", settings["d3d11_normal_y_mode"])
        self.assertEqual("force_no_flip", settings["normal_y_policy"]["d3d11_normal_y_mode"])
        self.assertTrue(settings["flip_texture_v"])
        self.assertTrue(settings["disable_all_support_maps"])
        self.assertAlmostEqual(0.25, settings["d3d11_roughness_bias"])
        self.assertAlmostEqual(0.9, settings["d3d11_metalness_scale"])
        self.assertAlmostEqual(1.7, settings["d3d11_emissive_gain"])

    def test_material_authority_report_flags_base_texture_reused_as_emissive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_emissiveIntensityTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
                "</SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_base.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=_dds(fourcc=b"DXT1"),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

            report = result.material_authority_report.to_dict()
            output = report["texture_outputs"][0]
            diagnostic_codes = {row["code"] for row in output["role_diagnostics"]}
            flags = set(report["risk_flags"])
            self.assertEqual(("Base / Color", "Emissive", "Normal"), output["bound_roles"])
            self.assertIn("_normalTexture", output["bound_parameters"])
            self.assertIn("base_texture_used_as_emissive", diagnostic_codes)
            self.assertIn("texture_bound_to_visible_and_technical_roles", diagnostic_codes)
            self.assertIn("multi_role_texture_binding", diagnostic_codes)
            self.assertIn("base_texture_used_as_emissive", flags)
            self.assertIn("visible_technical_role_conflict", flags)
            self.assertIn("ambiguous_texture_role_binding", flags)

    def test_material_authority_report_records_source_channel_gaps(self) -> None:
        preview = _preview("Glass")
        mesh = preview.preview_model.meshes[0]
        mesh.preview_texture_path = "glass_base.png"
        mesh.preview_alpha_mode = "BLEND"
        mesh.preview_native_material_overrides = {"emissive_intensity": 2.0}

        result = build_final_package_preview(preview)

        report = result.material_authority_report.to_dict()
        source_row = report["source_materials"][0]
        diagnostic_codes = {row["code"] for row in source_row["diagnostics"]}
        classes = {row["class"] for row in source_row["material_classification"]}
        flags = set(report["risk_flags"])
        section = source_row["sections"][0]
        self.assertEqual(1, source_row["section_count"])
        self.assertEqual(0, section["section_index"])
        self.assertEqual(-1, section["source_submesh_index"])
        self.assertEqual("Glass", section["section_name"])
        self.assertEqual(3, section["vertex_count"])
        self.assertEqual(1, section["face_count"])
        self.assertTrue(section["has_uvs"])
        self.assertFalse(section["has_normals"])
        self.assertEqual((0.0, 0.0, 0.0), section["bounds_min"])
        self.assertEqual((1.0, 1.0, 0.0), section["bounds_max"])
        self.assertNotIn("missing_source_material_sections", flags)
        self.assertIn("source_alpha_without_opacity_texture", diagnostic_codes)
        self.assertIn("source_emissive_scalar_no_texture", diagnostic_codes)
        self.assertIn("source_missing_roughness", diagnostic_codes)
        self.assertIn("source_missing_metalness", diagnostic_codes)
        self.assertNotIn("emissive", source_row["missing_channels"])
        self.assertIn("roughness", source_row["missing_channels"])
        self.assertIn("metalness", source_row["missing_channels"])
        self.assertIn("transparent_or_cutout", classes)
        self.assertIn("emissive", classes)
        self.assertIn("source_alpha_missing_opacity", flags)
        self.assertIn("source_missing_roughness_metalness", flags)
        self.assertIn("source_emissive_scalar_no_texture", flags)

    def test_material_authority_report_records_source_texture_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "source_base.dds"
            dds_path.write_bytes(_dds(width=8, height=4))
            preview = _preview("Blade", texture_path=str(dds_path))

            result = build_final_package_preview(preview, source_path=root / "source.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            self.assertIn("base", facts)
            self.assertEqual("dds", facts["base"]["image_format"])
            self.assertEqual((8, 4), tuple(facts["base"]["resolution"]))
            self.assertEqual("srgb", facts["base"]["color_space"])
            self.assertEqual("preview_texture_path", facts["base"]["source"])

    def test_material_authority_report_records_source_dds_channel_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "source_base.dds"
            dds_path.write_bytes(_dds_rgba_pixels([(10, 20, 30, 255), (110, 120, 130, 128)]))
            preview = _preview("Blade", texture_path=str(dds_path))

            result = build_final_package_preview(preview, source_path=root / "source.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            stats = dict(facts["base"]["channel_stats"])
            self.assertEqual("dds", facts["base"]["image_format"])
            self.assertEqual((2, 1), tuple(facts["base"]["resolution"]))
            self.assertEqual("available", facts["base"]["channel_stats_status"])
            self.assertAlmostEqual(60 / 255.0, stats["r_mean"], places=4)
            self.assertAlmostEqual(70 / 255.0, stats["g_mean"], places=4)
            self.assertAlmostEqual(80 / 255.0, stats["b_mean"], places=4)
            self.assertAlmostEqual(191.5 / 255.0, stats["a_mean"], places=4)
            self.assertAlmostEqual(128 / 255.0, stats["a_min"], places=4)

    def test_material_authority_report_records_source_texture_channel_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            png_path = root / "source_base.png"
            image = Image.new("RGBA", (2, 1))
            image.putdata([(64, 128, 255, 255), (128, 128, 0, 64)])
            image.save(png_path)
            preview = _preview("Blade", texture_path=str(png_path))

            result = build_final_package_preview(preview, source_path=root / "source.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            stats = dict(facts["base"]["channel_stats"])
            self.assertEqual("available", facts["base"]["channel_stats_status"])
            self.assertAlmostEqual(96 / 255.0, stats["r_mean"], places=4)
            self.assertAlmostEqual(128 / 255.0, stats["g_mean"], places=4)
            self.assertAlmostEqual(127.5 / 255.0, stats["b_mean"], places=4)
            self.assertAlmostEqual(159.5 / 255.0, stats["a_mean"], places=4)
            self.assertAlmostEqual(64 / 255.0, stats["a_min"], places=4)

    def test_material_authority_report_uses_base_alpha_texture_stats_as_opacity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            png_path = root / "glass_base.png"
            Image.new("RGBA", (2, 2), (90, 120, 160, 96)).save(png_path)
            preview = _preview("Glass", texture_path=str(png_path))
            preview.preview_model.meshes[0].preview_alpha_mode = "BLEND"

            result = build_final_package_preview(preview, source_path=root / "glass.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            diagnostic_codes = {row["code"] for row in source_row["diagnostics"]}
            self.assertIn("opacity", source_row["detected_channels"])
            self.assertIn("source_alpha_from_texture_channel", diagnostic_codes)
            self.assertNotIn("source_alpha_without_opacity_texture", diagnostic_codes)
            self.assertNotIn("source_alpha_missing_opacity", report["risk_flags"])

    def test_material_authority_report_treats_material_mask_alpha_as_technical_source_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_path = root / "plain_base.png"
            material_path = root / "plain_metallicRoughness.png"
            Image.new("RGBA", (2, 2), (220, 170, 40, 255)).save(base_path)
            Image.new("RGBA", (2, 2), (20, 80, 240, 64)).save(material_path)
            preview = _preview("PlainSurface", texture_path=str(base_path))
            mesh = preview.preview_model.meshes[0]
            mesh.preview_material_texture_path = str(material_path)
            mesh.preview_material_texture_subtype = "metallic_roughness"
            mesh.preview_material_texture_packed_channels = ("roughness", "metallic")

            result = build_final_package_preview(preview, source_path=root / "plain.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            diagnostics = {row["code"]: row for row in source_row["diagnostics"]}
            self.assertIn("source_packed_a_channel_technical", diagnostics)
            self.assertEqual("material", diagnostics["source_packed_a_channel_technical"]["slot_kind"])
            self.assertNotIn("source_alpha_from_texture_channel", diagnostics)
            self.assertNotIn("opacity", source_row["detected_channels"])
            self.assertNotIn("source_alpha_missing_opacity", report["risk_flags"])

    def test_material_authority_report_classifies_source_from_texture_channel_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_path = root / "plain_base.png"
            material_path = root / "plain_metallicRoughness.png"
            Image.new("RGBA", (2, 2), (220, 170, 40, 255)).save(base_path)
            Image.new("RGBA", (2, 2), (20, 80, 240, 255)).save(material_path)
            preview = _preview("PlainSurface", texture_path=str(base_path))
            mesh = preview.preview_model.meshes[0]
            mesh.preview_material_texture_path = str(material_path)
            mesh.preview_material_texture_subtype = "metallic_roughness"
            mesh.preview_material_texture_packed_channels = ("roughness", "metallic")

            result = build_final_package_preview(preview, source_path=root / "plain.glb")

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            classes = {row["class"]: row for row in source_row["material_classification"]}
            self.assertIn("metal", classes)
            self.assertIn("gold", classes)
            self.assertIn("B channel mean", classes["metal"]["evidence"])
            self.assertIn("yellow base texture mean", classes["gold"]["evidence"])

    def test_material_authority_report_reads_source_texture_facts_from_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "source_textures.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("textures/source_base.dds", _dds(width=16, height=8))
            preview = _preview("Blade", texture_path=f"{archive_path}::textures/source_base.dds")

            result = build_final_package_preview(preview, source_path=archive_path)

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            self.assertEqual("dds", facts["base"]["image_format"])
            self.assertEqual((16, 8), tuple(facts["base"]["resolution"]))
            self.assertEqual("srgb", facts["base"]["color_space"])

    def test_material_authority_report_reads_source_dds_stats_from_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "source_textures.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("textures/source_base.dds", _dds_rgba_pixels([(20, 40, 60, 255), (120, 140, 160, 255)], bgra=True))
            preview = _preview("Blade", texture_path=f"{archive_path}::textures/source_base.dds")

            result = build_final_package_preview(preview, source_path=archive_path)

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            stats = dict(facts["base"]["channel_stats"])
            self.assertEqual("dds", facts["base"]["image_format"])
            self.assertEqual((2, 1), tuple(facts["base"]["resolution"]))
            self.assertEqual("available", facts["base"]["channel_stats_status"])
            self.assertAlmostEqual(70 / 255.0, stats["r_mean"], places=4)
            self.assertAlmostEqual(90 / 255.0, stats["g_mean"], places=4)
            self.assertAlmostEqual(110 / 255.0, stats["b_mean"], places=4)

    def test_material_authority_report_reads_source_texture_stats_from_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image
            import io

            root = Path(temp_dir)
            archive_path = root / "source_textures.zip"
            buffer = io.BytesIO()
            Image.new("RGBA", (2, 2), (20, 40, 60, 128)).save(buffer, format="PNG")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("textures/source_base.png", buffer.getvalue())
            preview = _preview("Blade", texture_path=f"{archive_path}::textures/source_base.png")

            result = build_final_package_preview(preview, source_path=archive_path)

            report = result.material_authority_report.to_dict()
            source_row = report["source_materials"][0]
            facts = {row["slot_kind"]: row for row in source_row["texture_facts"]}
            stats = dict(facts["base"]["channel_stats"])
            self.assertEqual("png", facts["base"]["image_format"])
            self.assertEqual((2, 2), tuple(facts["base"]["resolution"]))
            self.assertEqual("available", facts["base"]["channel_stats_status"])
            self.assertAlmostEqual(20 / 255.0, stats["r_mean"], places=4)
            self.assertAlmostEqual(128 / 255.0, stats["a_mean"], places=4)

    def test_material_authority_report_records_vertex_color_source_channels(self) -> None:
        preview = _preview("VertexMetal")
        mesh = preview.preview_model.meshes[0]
        mesh.preview_texture_path = ""
        mesh.preview_vertex_color_mean = (0.90, 0.62, 0.14)
        mesh.preview_vertex_alpha_mean = 0.56
        mesh.preview_vertex_alpha_min = 0.38
        mesh.preview_native_material_overrides = {"metalness": 1.0, "roughness": 0.34}

        result = build_final_package_preview(preview)

        report = result.material_authority_report.to_dict()
        source_row = report["source_materials"][0]
        profile = source_row["channel_profile"]
        diagnostic_codes = {row["code"] for row in source_row["diagnostics"]}
        classes = {row["class"] for row in source_row["material_classification"]}
        self.assertEqual((0.9, 0.62, 0.14), source_row["vertex_color_factor"])
        self.assertEqual((0.56, 0.38), source_row["vertex_alpha"])
        self.assertIn("base_color_scalar", source_row["detected_channels"])
        self.assertIn("opacity_scalar", source_row["detected_channels"])
        self.assertIn("source_vertex_color_present", diagnostic_codes)
        self.assertIn("source_vertex_alpha_opacity", diagnostic_codes)
        self.assertEqual((0.9, 0.62, 0.14), profile["vertex_color_factor"])
        self.assertIn("gold", classes)
        self.assertIn("transparent_or_cutout", classes)

    def test_material_authority_report_classifies_named_source_material_families(self) -> None:
        def mesh(name: str, *, double_sided: bool = False, alpha_mode: str = "", metalness: float | None = None) -> ModelPreviewMesh:
            overrides = {}
            if metalness is not None:
                overrides["metalness"] = metalness
            return ModelPreviewMesh(
                material_name=name,
                positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                indices=[0, 1, 2],
                preview_texture_path=f"{name.lower()}_base.png",
                preview_alpha_mode=alpha_mode,
                preview_double_sided=double_sided,
                preview_native_material_overrides=overrides,
            )

        preview = MeshImportPreviewResult(
            rebuilt_data=b"not a parsed mesh in this focused test",
            parsed_mesh=ParsedMesh(path="character/model/source_families.pac", format="pac"),
            preview_model=ModelPreviewData(
                path="source_families.glb",
                meshes=[
                    mesh("PaintedMetalPanel", metalness=1.0),
                    mesh("CopperWire", metalness=1.0),
                    mesh("FlagCloth", double_sided=True),
                    mesh("LeatherWoodGrip"),
                    mesh("StoneBlock"),
                    mesh("OrganicFaceSkin"),
                    mesh("CrystalGlassLens", alpha_mode="BLEND"),
                ],
            ),
            summary_lines=[],
        )

        result = build_final_package_preview(preview)

        by_name = {
            row["material_name"]: {item["class"] for item in row["material_classification"]}
            for row in result.material_authority_report.to_dict()["source_materials"]
        }
        self.assertIn("metal", by_name["PaintedMetalPanel"])
        self.assertIn("painted_metal", by_name["PaintedMetalPanel"])
        self.assertIn("copper", by_name["CopperWire"])
        self.assertIn("cloth", by_name["FlagCloth"])
        self.assertIn("leather", by_name["LeatherWoodGrip"])
        self.assertIn("wood", by_name["LeatherWoodGrip"])
        self.assertIn("stone", by_name["StoneBlock"])
        self.assertIn("skin_organic", by_name["OrganicFaceSkin"])
        self.assertIn("glass_crystal", by_name["CrystalGlassLens"])
        self.assertIn("transparent_or_cutout", by_name["CrystalGlassLens"])

    def test_material_authority_report_uses_source_material_name_for_mapped_runtime_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("CD_PHM_02_Sword_0036")
            mesh = preview.preview_model.meshes[0]
            mesh.source_submesh_index = 1
            mesh.preview_texture_path = "gem_outside_base.png"
            preview.source_owned_output_draw_sections = (
                StaticOutputDrawSection(
                    0,
                    0,
                    "cd_phm_02_sword_0036",
                    [1],
                    0,
                    0,
                    "",
                    3,
                    False,
                    runtime_material_name="CD_PHM_02_Sword_0036",
                    source_material_name="Gem_outside",
                ),
            )
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem_base.dds",
                    target_path="character/texture/gem_base.dds",
                    kind="texture_generated",
                    payload_data=_dds(),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "gem.pac_xml",
                    target_path="character/modelproperty/gem.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar(
                        "character/texture/gem_base.dds",
                        "_overlayColorTexture",
                        "CD_PHM_02_Sword_0036",
                    ),
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

        report = result.material_authority_report.to_dict()
        source_row = report["source_materials"][0]
        output = report["texture_outputs"][0]
        classes = {row["class"] for row in source_row["material_classification"]}
        self.assertEqual("Gem_outside", source_row["material_name"])
        self.assertEqual("CD_PHM_02_Sword_0036", source_row["runtime_material_name"])
        self.assertEqual("Gem_outside", source_row["sections"][0]["section_name"])
        self.assertEqual(("Gem_outside",), tuple(output["conversion_policy"]["source_material_names"]))
        self.assertIn("glass_crystal", classes)
        self.assertNotIn("metal", classes)

    def test_material_authority_report_flags_spec_gloss_used_as_base_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = _preview("Blade")
            mesh = preview.preview_model.meshes[0]
            mesh.preview_texture_path = "blade_specularGlossiness.png"
            mesh.preview_material_texture_path = "blade_specularGlossiness.png"
            mesh.preview_material_texture_subtype = "specular_glossiness"
            mesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_specularGlossinessTexture",
                    preview_texture_path="blade_specularGlossiness.png",
                    semantic_type="material",
                    semantic_subtype="specular_glossiness",
                    packed_channels=("specular", "glossiness"),
                    visualized=True,
                ),
            )
            sidecar = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/blade_ma.dds"/>'
                "</MaterialParameterTexture></SkinnedMeshMaterialWrapper></Root>"
            ).encode("utf-8")
            specs = (
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade_ma.dds",
                    target_path="character/texture/blade_ma.dds",
                    kind="texture_generated",
                    payload_data=_dds(fourcc=b"DXT1"),
                    note="Generated packed material mask from source spec/gloss workflow.",
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.pac_xml",
                    target_path="character/modelproperty/blade.pac_xml",
                    kind="sidecar_generated",
                    payload_data=sidecar,
                ),
            )

            result = build_final_package_preview(preview, supplemental_file_specs=specs)

        report = result.material_authority_report.to_dict()
        source_row = report["source_materials"][0]
        mask_policy = {
            row["target_path"]: row["conversion_policy"]
            for row in report["texture_outputs"]
        }["character/texture/blade_ma.dds"]
        diagnostic_codes = {row["code"] for row in source_row["diagnostics"]}
        flags = set(report["risk_flags"])
        self.assertEqual("specular_glossiness", source_row["channel_profile"]["workflow"])
        self.assertIn("specular", source_row["detected_channels"])
        self.assertIn("glossiness", source_row["detected_channels"])
        self.assertIn("roughness", source_row["detected_channels"])
        self.assertIn("metalness", source_row["detected_channels"])
        self.assertEqual(("metalness", "roughness"), source_row["channel_profile"]["derived_channels"])
        self.assertNotIn("roughness", source_row["missing_channels"])
        self.assertNotIn("metalness", source_row["missing_channels"])
        self.assertIn("source_spec_gloss_derived_material_channels", diagnostic_codes)
        self.assertNotIn("source_missing_roughness", diagnostic_codes)
        self.assertNotIn("source_missing_metalness", diagnostic_codes)
        self.assertIn("source_spec_gloss_texture_as_base_color", diagnostic_codes)
        self.assertEqual(("specular_glossiness",), mask_policy["source_workflows"])
        self.assertEqual(("metalness", "roughness"), mask_policy["source_derived_channels"])
        self.assertTrue(mask_policy["spec_gloss_conversion"])
        self.assertIn("glossiness is inverted to roughness", mask_policy["spec_gloss_conversion_note"])
        self.assertIn("source_spec_gloss_base_conflict", flags)

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
