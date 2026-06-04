from __future__ import annotations

import unittest

from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_AUTHORITATIVE,
    AUTHORITY_GUESS,
    decode_crimson_texture_binding,
    decode_profile_for_family,
    normalize_shader_family,
    registry_manifest,
)


class CrimsonShaderRegistryTests(unittest.TestCase):
    def test_normalizes_target_shader_families(self) -> None:
        self.assertEqual("standard_v2", normalize_shader_family("SkinnedMeshStandard_Ver2"))
        self.assertEqual("cloth_v2", normalize_shader_family("SkinnedMeshClothVer2"))
        self.assertEqual("static_multitextured", normalize_shader_family("StaticMultiTextured"))
        self.assertEqual("skin", normalize_shader_family("SkinnedMeshSkin"))
        self.assertEqual("hair", normalize_shader_family("SkinnedMeshHairStandard"))

    def test_color_blending_mask_promotes_with_authority(self) -> None:
        decode = decode_crimson_texture_binding(
            shader_family="SkinnedMeshStandard_Ver2",
            parameter_name="_colorBlendingMaskTexture",
            source_path="character/texture/blade_ma.dds",
            slot_name="material",
            parameter_declared_by="pac_xml",
        )

        self.assertEqual(AUTHORITY_AUTHORITATIVE, decode["authority"])
        self.assertEqual("crimson_color_blending_mask", decode["source_kind"])
        self.assertEqual("promoted", decode["disposition"])
        self.assertEqual({"ao": "r", "roughness": "g", "metalness": "b"}, decode["promoted_channels"])

    def test_unknown_crimson_material_map_stays_diagnostic_guess(self) -> None:
        decode = decode_crimson_texture_binding(
            shader_family="MysteryShader",
            parameter_name="",
            source_path="character/texture/blade_ma.dds",
            slot_name="material",
        )

        self.assertEqual(AUTHORITY_GUESS, decode["authority"])
        self.assertEqual("diagnostic_only", decode["disposition"])
        self.assertEqual({}, decode["promoted_channels"])

    def test_detail_grime_and_hair_controls_are_layer_only(self) -> None:
        cases = (
            ("_detailMaskTexture", "blade_mg.dds", "layer_only"),
            ("_detailDiffuseMaskR", "layer_color.dds", "layer_only"),
            ("_detailNormalMaskR", "layer_normal_n.dds", "layer_only"),
            ("_detailHeightMaskR", "layer_height_disp.dds", "layer_only"),
            ("_skinDetailMaskTexture", "skin_mask_mg.dds", "layer_only"),
            ("_wrinkleMaskTexture0", "skin_wrinkle_mask.dds", "layer_only"),
            ("_baseColorTexture1", "layer1.dds", "layer_only"),
            ("_colorTextureG", "layer_g.dds", "layer_only"),
            ("_normalTexture1", "layer1_n.dds", "layer_only"),
            ("_heightTextureB", "layer_b_disp.dds", "layer_only"),
            ("_grimeDiffuseTextureR", "grime.dds", "layer_only"),
            ("_grimeNormalTextureR", "grime_n.dds", "layer_only"),
            ("_grimeMaterialTextureR", "blade_sp.dds", "layer_material_response"),
            ("_ssdmDirectionTexture", "hair_dir.dds", "layer_direction"),
        )
        for parameter_name, path, disposition in cases:
            with self.subTest(parameter_name=parameter_name):
                decode = decode_crimson_texture_binding(
                    shader_family="SkinnedMeshStandard_Ver2",
                    parameter_name=parameter_name,
                    source_path=path,
                    slot_name="material",
                    parameter_declared_by="pac_xml",
                )
                self.assertEqual(AUTHORITY_AUTHORITATIVE, decode["authority"])
                self.assertEqual(disposition, decode["disposition"])
                self.assertFalse(decode["promoted_channels"])

    def test_family_specific_layer_slots_are_authoritative_but_not_global_promotions(self) -> None:
        cases = (
            ("SkinnedMeshSkin", "_skinDetailMaterialTexture", "skin_detail_sp.dds", "crimson_skin_material_response"),
            ("SkinnedMeshHairStandard", "_materialTexture", "hair_sp.dds", "crimson_hair_material_response"),
            ("StaticMultiTextured", "_rgbTexture", "layer_rgb.dds", "crimson_static_multitextured_layer_color"),
            ("StaticMultiTextured", "_layerBlendMaskTexture", "layer_mask.dds", "crimson_static_multitextured_blend_mask"),
        )
        for family, parameter_name, path, source_kind in cases:
            with self.subTest(parameter_name=parameter_name):
                decode = decode_crimson_texture_binding(
                    shader_family=family,
                    parameter_name=parameter_name,
                    source_path=path,
                    parameter_declared_by="pac_xml",
                )

                self.assertEqual("authoritative", decode["authority"])
                self.assertEqual(source_kind, decode["source_kind"])
                self.assertFalse(decode["promoted_channels"])

    def test_registry_manifest_lists_authority_values(self) -> None:
        manifest = registry_manifest()

        self.assertEqual(1, manifest["schema_version"])
        self.assertIn("standard_v2", [family["family"] for family in manifest["families"]])
        self.assertIn("authoritative", manifest["authority_values"])
        self.assertEqual("checklist_only", decode_profile_for_family("Hair")["renderdoc_truth_pass"]["status"])


if __name__ == "__main__":
    unittest.main()
