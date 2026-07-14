from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import unittest
from unittest.mock import patch

from cdmw.core.archive import (
    _ArchiveModelSidecarTextureBinding,
    _archive_texture_family_mismatch_summary,
    _attach_model_sidecar_texture_preview_paths,
    _attach_model_texture_preview_paths,
    _attach_model_support_texture_preview_paths,
    _build_model_preview_texture_slot_detail_text,
    _iter_model_sidecar_binding_submesh_keys,
    normalize_texture_reference_for_sidecar_lookup,
)
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings
from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialParameterInput,
)


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0000/0.pamt"),
        paz_file=Path("0000/1.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def _texture_maps(*paths: str):
    by_normalized = defaultdict(list)
    by_basename = defaultdict(list)
    for path in paths:
        entry = _entry(path)
        by_normalized[normalize_texture_reference_for_sidecar_lookup(path)].append(entry)
        by_basename[Path(path).name.lower()].append(entry)
    return by_normalized, by_basename


class ArchivePreviewTextureBindingTests(unittest.TestCase):
    def test_sidecar_material_contract_applies_without_resolved_texture(self) -> None:
        source_entry = _entry("character/model/cd_test_cloth.pac")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Cloth")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/missing_cloth.dds",
                parameter_name="_baseColorTexture",
                submesh_name="CD_Test_Cloth",
                sidecar_kind="pac_xml",
                shader_family="SkinnedMeshStandard",
                material_parameters=(
                    PreviewMaterialParameterInput(
                        parameter_kind="uint",
                        parameter_name="AlphaTest",
                        value="1",
                        numeric_value=1.0,
                    ),
                    PreviewMaterialParameterInput(
                        parameter_kind="float",
                        parameter_name="AlphaRef",
                        value="128",
                        numeric_value=128.0,
                    ),
                    PreviewMaterialParameterInput(
                        parameter_kind="bool",
                        parameter_name="DoubleSided",
                        value="true",
                        numeric_value=1.0,
                    ),
                ),
            ),
        )

        lines = _attach_model_sidecar_texture_preview_paths(
            None,
            source_entry,
            model,
            parsed_mesh=None,
            sidecar_texture_bindings=bindings,
        )

        mesh = model.meshes[0]
        self.assertEqual("SkinnedMeshStandard", mesh.preview_sidecar_shader_family)
        self.assertEqual("cutout", mesh.preview_alpha_mode)
        self.assertAlmostEqual(128.0 / 255.0, mesh.preview_native_material_overrides["alpha_cutoff"])
        self.assertTrue(mesh.preview_double_sided)
        self.assertEqual(bindings[0].material_parameters, mesh.preview_material_parameters)
        self.assertTrue(any("independently of texture resolution" in line for line in lines))

    def test_sidecar_layer_opacity_names_do_not_enable_surface_blending(self) -> None:
        source_entry = _entry("character/model/cd_test_weapon.pac")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Weapon")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/missing_weapon.dds",
                parameter_name="_baseColorTexture",
                submesh_name="CD_Test_Weapon",
                material_parameters=(
                    PreviewMaterialParameterInput(
                        parameter_kind="uint",
                        parameter_name="_colorBlendingFlag",
                        value="1",
                        numeric_value=1.0,
                    ),
                    PreviewMaterialParameterInput(
                        parameter_kind="float",
                        parameter_name="_dyeingGlobalOpacity",
                        value="0.5",
                        numeric_value=0.5,
                    ),
                ),
            ),
        )

        _attach_model_sidecar_texture_preview_paths(
            None,
            source_entry,
            model,
            parsed_mesh=None,
            sidecar_texture_bindings=bindings,
        )

        self.assertEqual("", model.meshes[0].preview_alpha_mode)

    def test_texture_slot_detail_text_lists_part_to_dds_mapping(self) -> None:
        model = ModelPreviewData(
            path="character/model/cloth.pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_PHM_00_Cloak_0054",
                    texture_name="cd_phm_00_cloak_0054.dds",
                    preview_normal_texture_name="cd_phm_00_cloak_0054_n.dds",
                    preview_material_texture_name="cd_phm_00_cloak_0054_sp.dds",
                    preview_material_texture_type="mask",
                    preview_material_texture_subtype="specular",
                    preview_material_texture_packed_channels=("specular",),
                    preview_height_texture_name="cd_phm_00_cloak_0054_disp.dds",
                )
            ],
        )

        text = _build_model_preview_texture_slot_detail_text(model)

        self.assertIn("Texture Slot Mapping", text)
        self.assertIn("CD_PHM_00_Cloak_0054 -> base DDS=cd_phm_00_cloak_0054.dds", text)
        self.assertIn("normal DDS=cd_phm_00_cloak_0054_n.dds", text)
        self.assertIn("material DDS=cd_phm_00_cloak_0054_sp.dds", text)
        self.assertIn("height DDS=cd_phm_00_cloak_0054_disp.dds", text)
        self.assertIn("decoded channels=mask/specular/specular", text)

    def test_sidecar_binding_resolves_common_texture_folder_variant(self) -> None:
        source_entry = _entry("character/model/body_a.pac")
        by_normalized, by_basename = _texture_maps("character/body_a.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Body", texture_name="Body")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/body_a.dds",
                parameter_name="_baseColorTexture",
                submesh_name="Body",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/body_a.dds", model.meshes[0].texture_name)
        self.assertEqual("preview://character/body_a.dds", model.meshes[0].preview_texture_path)

    def test_cross_component_sidecar_binding_does_not_replace_current_pac_mesh(self) -> None:
        source_entry = _entry("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac")
        by_normalized, by_basename = _texture_maps("character/texture/cd_texturelayer_001_0101.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_PHM_00_Head_0001_01",
                    texture_name="character/texture/cd_phm_00_head_00_0001_01.dds",
                )
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_texturelayer_001_0101.dds",
                parameter_name="_detailDiffuseMaskR",
                submesh_name="CD_PHM_00_UW_00_0001",
                sidecar_kind="pac_xml",
                sidecar_path="character/modelproperty/1_pc/1_phm/armor/38_underwear/cd_phm_00_uw_00_0001.pac_xml",
                linked_mesh_path="character/model/1_pc/1_phm/armor/38_underwear/cd_phm_00_uw_00_0001.pac",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/cd_phm_00_head_00_0001_01.dds", model.meshes[0].texture_name)
        self.assertEqual("", model.meshes[0].preview_texture_path)
        self.assertEqual([], lines)

    def test_pac_xml_parser_uses_first_model_property_material_group(self) -> None:
        sidecar_text = (
            "<Root>"
            "<ModelProperty>"
            '<SkinnedMeshMaterialWrapper _subMeshName="Body_A">'
            '<MaterialParameterTexture _name="_baseColorTexture">'
            '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'
            "</MaterialParameterTexture>"
            "</SkinnedMeshMaterialWrapper>"
            "</ModelProperty>"
            "<ModelProperty>"
            '<SkinnedMeshMaterialWrapper _subMeshName="Body_B">'
            '<MaterialParameterTexture _name="_baseColorTexture">'
            '<ResourceReferencePath_ITexture value="character/texture/body_b.dds"/>'
            "</MaterialParameterTexture>"
            "</SkinnedMeshMaterialWrapper>"
            "</ModelProperty>"
            "</Root>"
        )

        bindings = parse_texture_sidecar_bindings(
            sidecar_text,
            sidecar_path="character/modelproperty/body_a.pac_xml",
        )

        self.assertEqual(1, len(bindings))
        self.assertEqual("Body_A", bindings[0].submesh_name)
        self.assertEqual("character/texture/body_a.dds", bindings[0].texture_path)
        self.assertEqual("base", bindings[0].layer_role)
        self.assertEqual("srgb", bindings[0].srgb_mode)
        self.assertEqual("pac_xml", bindings[0].parameter_declared_by)
        self.assertEqual("exact", bindings[0].material_output_quality)
        self.assertIn("role:base", bindings[0].blend_flags)

    def test_cross_family_sidecar_texture_notice_is_explicit_but_nonfatal(self) -> None:
        notice = _archive_texture_family_mismatch_summary(
            "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0054_16.pac",
            (
                "character/texture/cd_m0002_00_wolf_eye_0001.dds",
                "character/texture/cd_m0002_00_wolf_hair_0001.dds",
            ),
            sidecar_paths=("character/modelproperty/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0054_16.pac_xml",),
        )

        self.assertIn("Cross-family material notice", notice)
        self.assertIn("wolf", notice)
        self.assertIn("cloak", notice)
        self.assertIn("not proof of item identity", notice)

    def test_matching_sidecar_texture_family_has_no_notice(self) -> None:
        notice = _archive_texture_family_mismatch_summary(
            "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0054_16.pac",
            ("character/texture/cd_phm_00_cloak_0054_16_d.dds",),
        )

        self.assertEqual("", notice)

    def test_sidecar_binding_keys_prefer_explicit_part_over_linked_model_path(self) -> None:
        binding = _ArchiveModelSidecarTextureBinding(
            texture_path="character/texture/part_b.dds",
            parameter_name="_baseColorTexture",
            submesh_name="CD_Test_Part_B",
            linked_mesh_path="character/model/cd_test_model.pac",
        )

        keys = _iter_model_sidecar_binding_submesh_keys(binding)

        self.assertIn("cdtestpartb", keys)
        self.assertNotIn("cdtestmodel", keys)

    def test_anonymous_meshes_use_ordered_sidecar_visible_bindings(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/part_a.dds",
            "character/texture/part_b.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="unknown_10", texture_name="unknown_10"),
                ModelPreviewMesh(material_name="unknown_20", texture_name="unknown_20"),
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/part_a.dds",
                parameter_name="_diffuseTextureR",
                submesh_name="CD_Test_Part_A",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/part_b.dds",
                parameter_name="_diffuseTextureR",
                submesh_name="CD_Test_Part_B",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a.dds", model.meshes[0].texture_name)
        self.assertEqual("character/texture/part_b.dds", model.meshes[1].texture_name)
        self.assertIn("ordered sidecar material wrapper", "\n".join(lines))

    def test_named_unresolved_mesh_does_not_promote_unrelated_sidecar_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/part_a.dds",
            "character/texture/part_b_n.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="CD_Test_Part_A", texture_name="CD_Test_Part_A"),
                ModelPreviewMesh(material_name="CD_Test_Part_B", texture_name="CD_Test_Part_B"),
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/part_a.dds",
                parameter_name="_diffuseTextureR",
                submesh_name="CD_Test_Part_A",
                sidecar_kind="pac_xml",
                tint_color=(0.8, 0.1, 0.1),
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/part_b_n.dds",
                parameter_name="_normalTexture",
                submesh_name="CD_Test_Part_B",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a.dds", model.meshes[0].texture_name)
        self.assertEqual("preview://character/texture/part_a.dds", model.meshes[0].preview_texture_path)
        self.assertEqual("CD_Test_Part_B", model.meshes[1].texture_name)
        self.assertEqual("", model.meshes[1].preview_texture_path)
        self.assertNotIn("Used a sidecar texture fallback", "\n".join(lines))

    def test_sidecar_overlay_base_promotes_material_tint_to_preview_color(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("character/texture/cd_common_default_overlay_old.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_common_default_overlay_old.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
                tint_color=(0.62, 0.31, 0.14),
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="mesh_base_first",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual((0.62, 0.31, 0.14), model.meshes[0].preview_color)
        self.assertEqual("low_authority_overlay", model.meshes[0].preview_base_texture_quality)
        self.assertIn("low-detail overlay/default", model.meshes[0].preview_texture_approximation_note)

    def test_layer_visible_sidecar_texture_replaces_low_authority_overlay_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/cd_common_default_overlay_old.dds",
            "character/texture/cd_texturelayer_001_0001.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_common_default_overlay_old.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_texturelayer_001_0001.dds",
                parameter_name="_detailDiffuseMaskR",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="mesh_base_first",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                fallback_only=True,
            )

        self.assertEqual("character/texture/cd_texturelayer_001_0001.dds", model.meshes[0].texture_name)
        self.assertEqual(
            "preview://character/texture/cd_texturelayer_001_0001.dds",
            model.meshes[0].preview_texture_path,
        )
        self.assertEqual("resolved_base", model.meshes[0].preview_base_texture_quality)
        self.assertIn("Promoted 1 sidecar visible layer texture preview", "\n".join(lines))

    def test_detail_layer_visible_texture_beats_grime_layer_for_promoted_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/cd_common_default_overlay_old.dds",
            "character/texture/cd_texturelayer_003_0102.dds",
            "character/texture/cd_texturelayer_001_0034.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Shield", texture_name="CD_Test_Shield")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_common_default_overlay_old.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Shield",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_texturelayer_003_0102.dds",
                parameter_name="_grimeDiffuseTextureR",
                submesh_name="CD_Test_Shield",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_texturelayer_001_0034.dds",
                parameter_name="_detailDiffuseMaskR",
                submesh_name="CD_Test_Shield",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="mesh_base_first",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                fallback_only=True,
            )

        self.assertEqual("character/texture/cd_texturelayer_001_0034.dds", model.meshes[0].texture_name)
        self.assertEqual(
            "preview://character/texture/cd_texturelayer_001_0034.dds",
            model.meshes[0].preview_texture_path,
        )
        self.assertIn("Promoted 1 sidecar visible layer texture preview", "\n".join(lines))

    def test_technical_sidecar_texture_does_not_replace_low_authority_overlay_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/cd_common_default_overlay_old.dds",
            "character/texture/cd_test_handle_n.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_common_default_overlay_old.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_test_handle_n.dds",
                parameter_name="_normalTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="mesh_base_first",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                fallback_only=True,
            )

        self.assertEqual("character/texture/cd_common_default_overlay_old.dds", model.meshes[0].texture_name)
        self.assertEqual(
            "preview://character/texture/cd_common_default_overlay_old.dds",
            model.meshes[0].preview_texture_path,
        )
        self.assertEqual("low_authority_overlay", model.meshes[0].preview_base_texture_quality)
        self.assertNotIn("Promoted", "\n".join(lines))

    def test_direction_vector_sidecar_texture_does_not_become_visible_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/cd_test_cloak_o.dds",
            "character/texture/cd_test_cloak_dr.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Cloak", texture_name="CD_Test_Cloak")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_test_cloak_o.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Cloak",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_test_cloak_dr.dds",
                parameter_name="_directionTexture",
                submesh_name="CD_Test_Cloak",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("preview://character/texture/cd_test_cloak_o.dds", model.meshes[0].preview_texture_path)
        self.assertNotEqual("preview://character/texture/cd_test_cloak_dr.dds", model.meshes[0].preview_texture_path)

    def test_placeholder_none_texture_does_not_become_visible_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("texture/nonetexture0x00000000.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="texture/nonetexture0x00000000.dds",
                parameter_name="_diffuseTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
                tint_color=(0.5, 0.49, 0.48),
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_texture_path)
        self.assertEqual("CD_Test_Handle", model.meshes[0].texture_name)
        self.assertEqual("material_color_fallback", model.meshes[0].preview_base_texture_quality)
        self.assertIn("material color fallback", "\n".join(lines))

    def test_placeholder_none_texture_is_skipped_when_promoting_layer_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/cd_common_default_overlay_old.dds",
            "texture/nonetexture0x00000000.dds",
            "character/texture/cd_texturelayer_003_0005.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_common_default_overlay_old.dds",
                parameter_name="_overlayColorTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="texture/nonetexture0x00000000.dds",
                parameter_name="_grimeDiffuseTextureR",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/cd_texturelayer_003_0005.dds",
                parameter_name="_detailDiffuseMaskR",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="mesh_base_first",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_sidecar_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                fallback_only=True,
            )

        self.assertEqual("character/texture/cd_texturelayer_003_0005.dds", model.meshes[0].texture_name)
        self.assertEqual(
            "preview://character/texture/cd_texturelayer_003_0005.dds",
            model.meshes[0].preview_texture_path,
        )

    def test_emissive_sidecar_binding_uses_emissive_channel_not_base(self) -> None:
        source_entry = _entry("character/model/cd_test_lantern.pac")
        emissive_path = "character/texture/cd_test_lantern_emissive.dds"
        by_normalized, by_basename = _texture_maps(emissive_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Lantern")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path=emissive_path,
                parameter_name="_emissiveTexture",
                submesh_name="CD_Test_Lantern",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        self.assertEqual("", mesh.preview_texture_path)
        self.assertEqual(f"preview://{emissive_path}", mesh.preview_emissive_texture_path)
        self.assertEqual(emissive_path, mesh.preview_emissive_texture_name)
        self.assertEqual("emissive", mesh.preview_material_texture_inputs[0].semantic_type)
        self.assertIn("Exact sidecar emissive bindings", "\n".join(lines))

    def test_base_texture_is_not_reused_as_emissive_sibling_fallback(self) -> None:
        source_entry = _entry("character/model/cd_test_cloth.pac")
        base_path = "character/texture/cd_test_cloth.dds"
        by_normalized, by_basename = _texture_maps(base_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Cloth",
                    texture_name=base_path,
                    preview_texture_path=f"preview://{base_path}",
                )
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_emissive_texture_path)
        self.assertNotIn("emissive bindings", "\n".join(lines))

    def test_emissive_sibling_fallback_requires_matching_material_family(self) -> None:
        source_entry = _entry("character/model/cd_test_sword.pac")
        blade_emissive = "character/texture/cd_test_blade_0014_emi.dds"
        by_normalized, by_basename = _texture_maps(blade_emissive)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Blade_0014",
                    texture_name="CD_Test_Blade_0014",
                ),
                ModelPreviewMesh(
                    material_name="CD_Test_Handle_0014",
                    texture_name="CD_Test_Handle_0014",
                ),
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual(f"preview://{blade_emissive}", model.meshes[0].preview_emissive_texture_path)
        self.assertEqual("", model.meshes[1].preview_emissive_texture_path)

    def test_anonymous_wrapper_order_does_not_spread_emissive_maps(self) -> None:
        source_entry = _entry("character/model/cd_test_sword.pac")
        paths = (
            "character/texture/cd_test_blade_0014_emi.dds",
            "character/texture/cd_test_acc_0037_emi.dds",
        )
        by_normalized, by_basename = _texture_maps(*paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="unknown_10"),
                ModelPreviewMesh(material_name="unknown_20"),
            ],
        )
        bindings = tuple(
            _ArchiveModelSidecarTextureBinding(
                texture_path=path,
                parameter_name="_emissiveIntensityTexture",
                submesh_name=f"wrapper_{index}",
            )
            for index, path in enumerate(paths)
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertTrue(all(not mesh.preview_emissive_texture_path for mesh in model.meshes))

    def test_placeholder_none_texture_is_not_applied_as_support_map(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("texture/nonetexture0x00000000.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="texture/nonetexture0x00000000.dds",
                parameter_name="_normalTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_normal_texture_path)
        self.assertNotIn("Exact sidecar normal-map bindings", "\n".join(lines))

    def test_sidecar_material_color_survives_missing_visible_dds(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps()
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Blade", texture_name="CD_Test_Blade")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/missing_base.dds",
                parameter_name="_baseColorTexture",
                submesh_name="CD_Test_Blade",
                sidecar_kind="pac_xml",
                tint_color=(0.22, 0.26, 0.42),
            ),
        )

        lines = _attach_model_sidecar_texture_preview_paths(
            Path("texconv.exe"),
            source_entry,
            model,
            parsed_mesh=None,
            sidecar_texture_bindings=bindings,
            visible_texture_mode="mesh_base_first",
            texture_entries_by_normalized_path=by_normalized,
            texture_entries_by_basename=by_basename,
        )

        self.assertEqual((0.22, 0.26, 0.42), model.meshes[0].preview_color)
        self.assertEqual("", model.meshes[0].preview_texture_path)
        self.assertEqual("material_color_fallback", model.meshes[0].preview_base_texture_quality)
        self.assertIn("material color fallback", "\n".join(lines))

    def test_material_name_base_fallback_uses_visible_sibling_dds(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/part_a_d.dds",
            "character/texture/part_a_n.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="part_a", texture_name="part_a")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a_d.dds", model.meshes[0].texture_name)
        self.assertEqual("preview://character/texture/part_a_d.dds", model.meshes[0].preview_texture_path)

    def test_material_name_base_correction_can_replace_sidecar_layer_fallback(self) -> None:
        source_entry = _entry("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac")
        head_texture = "character/texture/cd_phm_00_head_00_0001_01.dds"
        layer_texture = "character/texture/cd_texturelayer_001_0101.dds"
        by_normalized, by_basename = _texture_maps(head_texture, layer_texture)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_PHM_00_Head_0001_01",
                    texture_name=head_texture,
                    preview_texture_path=f"preview://{layer_texture}",
                    preview_base_texture_source="pac_xml",
                )
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                override_existing_base=True,
                prefer_material_name_for_base=True,
            )

        self.assertEqual(head_texture, model.meshes[0].texture_name)
        self.assertEqual(f"preview://{head_texture}", model.meshes[0].preview_texture_path)
        self.assertIn("Corrected 1 mesh base texture preview", "\n".join(lines))

    def test_technical_sibling_dds_is_not_promoted_to_visible_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("character/texture/part_a_n.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="part_a", texture_name="part_a")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("part_a", model.meshes[0].texture_name)
        self.assertEqual("", model.meshes[0].preview_texture_path)

    def test_anonymous_meshes_use_ordered_sidecar_support_bindings(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = (
            "character/texture/part_a_n.dds",
            "character/texture/part_b_n.dds",
            "character/texture/part_a_ma.dds",
            "character/texture/part_b_ma.dds",
            "character/texture/part_a_disp.dds",
            "character/texture/part_b_disp.dds",
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="unknown_10", texture_name="unknown_10"),
                ModelPreviewMesh(material_name="unknown_20", texture_name="unknown_20"),
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_n.dds", "_normalTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_n.dds", "_normalTexture", "Part_B"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_ma.dds", "_materialTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_ma.dds", "_materialTexture", "Part_B"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_disp.dds", "_heightTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_disp.dds", "_heightTexture", "Part_B"),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a_n.dds", model.meshes[0].preview_normal_texture_name)
        self.assertEqual("character/texture/part_b_n.dds", model.meshes[1].preview_normal_texture_name)
        self.assertEqual("character/texture/part_a_ma.dds", model.meshes[0].preview_material_texture_name)
        self.assertEqual("character/texture/part_b_disp.dds", model.meshes[1].preview_height_texture_name)
        self.assertIn("anonymous support-map", "\n".join(lines))

    def test_exact_sidecar_support_preserves_multiple_material_inputs_for_preview(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = (
            "character/texture/part_a_ma.dds",
            "character/texture/part_a_sp.dds",
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_ma.dds", "_materialTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding(
                "character/texture/part_a_sp.dds",
                "_specularTexture",
                "Part_A",
                srgb_mode="linear",
                parameter_declared_by="pac_xml",
                material_output_quality="layer",
                layer_role="material_response",
                layer_channel="g",
                blend_flags=("role:material_response", "channel:g"),
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda _texconv, texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_inputs = [
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.slot_kind == "material"
        ]
        self.assertEqual(
            {
                "character/texture/part_a_ma.dds",
                "character/texture/part_a_sp.dds",
            },
            {item.source_texture_path for item in material_inputs},
        )
        specular_input = next(item for item in material_inputs if item.source_texture_path.endswith("_sp.dds"))
        self.assertEqual("character/texture/part_a_sp.dds", specular_input.source_dds_path)
        self.assertEqual("linear", specular_input.srgb_mode)
        self.assertEqual("pac_xml", specular_input.parameter_declared_by)
        self.assertEqual("layer", specular_input.material_output_quality)
        self.assertEqual("material_response", specular_input.layer_role)
        self.assertEqual("g", specular_input.layer_channel)
        self.assertIn("channel:g", specular_input.blend_flags)
        self.assertIn("material diagnostics and preview", "\n".join(lines))

    def test_exact_sidecar_material_inputs_are_capped_before_preview_conversion(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = tuple(
            f"character/texture/part_a_layer_{index:02d}_ma.dds"
            for index in range(8)
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        bindings = tuple(
            _ArchiveModelSidecarTextureBinding(path, f"_materialTexture{index}", "Part_A")
            for index, path in enumerate(texture_paths)
        )
        converted_paths: list[str] = []

        def _preview_path(_texconv, texture_entry, **_kwargs):
            converted_paths.append(texture_entry.path)
            return f"preview://{texture_entry.path}"

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=_preview_path,
        ):
            lines = _attach_model_support_texture_preview_paths(
                Path("texconv.exe"),
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_inputs = [
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.slot_kind == "material"
        ]
        # One input is the active material slot itself; rich sidecar inputs are
        # capped before conversion so high-layer sidecars do not spawn dozens
        # of texconv jobs on the cold preview path.
        self.assertLessEqual(len(material_inputs), 6)
        self.assertLessEqual(len(set(converted_paths)), 5)
        self.assertIn("lower-priority sidecar material texture input", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
