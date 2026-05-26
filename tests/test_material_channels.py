from __future__ import annotations

import unittest

from cdmw.rendering.material_channels import (
    MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
    parse_crimson_material_definition_text,
    resolve_preview_batch_material_channels,
)


class MaterialChannelContractTests(unittest.TestCase):
    def test_material_channel_schema_is_v2(self) -> None:
        self.assertEqual(2, MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION)

    def test_resolves_sketchfab_style_explicit_pbr_channels(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "painted_metal",
                "textures": {
                    "base": "textures/base.png",
                    "normal": "textures/normal.png",
                    "roughness": "textures/roughness.png",
                    "metalness": "textures/metalness.png",
                    "occlusion": "textures/ao.png",
                },
                "material_contract": {
                    "shader_family": "standard",
                    "pbr_scalar_hints": {"roughness": 0.42, "metalness": 0.7},
                    "texture_slots": {
                        "base": {"confidence": "exact", "diagnostic": "declared albedo"},
                        "roughness": {"confidence": "exact", "diagnostic": "declared roughness"},
                        "metalness": {"confidence": "exact", "diagnostic": "declared metalness"},
                    },
                },
            }
        )

        self.assertEqual("metallic_roughness", contract.workflow)
        self.assertEqual("AlbedoPBR", contract.channel("base_color").sketchfab_channel)
        self.assertEqual("RoughnessPBR", contract.channel("roughness").sketchfab_channel)
        self.assertEqual("MetalnessPBR", contract.channel("metalness").sketchfab_channel)
        self.assertEqual("AOPBR", contract.channel("ao").sketchfab_channel)
        self.assertEqual("srgb", contract.channel("base_color").color_space)
        self.assertEqual("linear", contract.channel("roughness").color_space)
        self.assertEqual([], list(contract.unresolved))

    def test_base_color_parameter_preserves_source_dds_and_parameter(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_base",
                "textures": {"base": "previews/body.png"},
                "material_contract": {
                    "shader_family": "SkinnedMeshStandard_Ver2",
                    "texture_slots": {
                        "base": {
                            "parameter_name": "_baseColorTexture",
                            "source_dds_path": "character/texture/body_d.dds",
                            "confidence": "sidecar",
                            "source_kind": "direct_dds",
                        }
                    },
                },
            }
        )

        channel = contract.channel("base_color")
        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual("_baseColorTexture", channel.parameter_name)
        self.assertEqual("character/texture/body_d.dds", channel.source_dds_path)
        self.assertEqual("sidecar", channel.confidence)
        self.assertEqual("direct_dds", channel.source_kind)

    def test_specular_glossiness_workflow_is_detected(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "legacy_spec_gloss",
                "textures": {
                    "base": "textures/diffuse.png",
                    "specular": "textures/spec.png",
                    "glossiness": "textures/gloss.png",
                },
            }
        )

        self.assertEqual("specular_glossiness", contract.workflow)
        self.assertEqual("SpecularPBR", contract.channel("specular").sketchfab_channel)
        self.assertEqual("GlossinessPBR", contract.channel("glossiness").sketchfab_channel)

    def test_texture_slot_srgb_mode_overrides_default_specular_space(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "linear_spec",
                "textures": {"specular": "textures/weapon_sp.dds"},
                "material_contract": {
                    "texture_slots": {
                        "specular": {
                            "confidence": "exact",
                            "srgb_mode": "linear",
                        }
                    }
                },
            }
        )

        self.assertEqual("linear", contract.channel("specular").color_space)

    def test_packed_crimson_material_mask_stays_unresolved(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_material",
                "textures": {"base": "textures/base.png", "material": "textures/material_sp.png"},
                "material_contract": {
                    "packed_channels": ["unknown_r", "unknown_g", "unknown_b"],
                    "texture_slots": {
                        "material": {
                            "confidence": "approximate",
                            "diagnostic": "Crimson material mask",
                        }
                    },
                },
            }
        )

        self.assertIsNone(contract.channel("roughness"))
        self.assertIsNone(contract.channel("metalness"))
        self.assertTrue(any(item.get("slot") == "material" for item in contract.unresolved))

    def test_crimson_ma_material_map_promotes_ao_roughness_and_metalness(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_material",
                "textures": {"material": "textures/cd_phm_02_blade_0014_ma.png"},
                "material_contract": {
                    "shader_family": "SkinnedMeshStandard_Ver2",
                    "texture_slots": {
                        "material": {
                            "parameter_name": "_colorBlendingMaskTexture",
                            "shader_family": "SkinnedMeshStandard_Ver2",
                            "confidence": "authoritative",
                        }
                    },
                },
            }
        )

        self.assertEqual("r", contract.channel("ao").source_channel)
        self.assertEqual("g", contract.channel("roughness").source_channel)
        self.assertEqual("b", contract.channel("metalness").source_channel)
        self.assertEqual("crimson_color_blending_mask", contract.channel("metalness").source_kind)
        self.assertEqual("shader_parameter_rule", contract.channel("roughness").confidence)
        self.assertEqual("_colorBlendingMaskTexture", contract.channel("metalness").parameter_name)
        self.assertFalse(contract.unresolved)

    def test_bare_crimson_ma_material_map_stays_unresolved_without_parameter_rule(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_material",
                "textures": {"material": "textures/cd_phm_02_blade_0014_ma.png"},
            }
        )

        self.assertIsNone(contract.channel("roughness"))
        self.assertIsNone(contract.channel("metalness"))
        self.assertTrue(any(item.get("disposition") == "diagnostic_only" for item in contract.unresolved))

    def test_detail_mask_mg_is_layer_only_not_global_pbr(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_material",
                "textures": {"material": "textures/cd_phm_02_blade_0014_mg.png"},
                "material_contract": {
                    "shader_family": "SkinnedMeshStandard_Ver2",
                    "texture_slots": {
                        "material": {
                            "parameter_name": "_detailMaskTexture",
                            "shader_family": "SkinnedMeshStandard_Ver2",
                            "confidence": "authoritative",
                        }
                    },
                },
            }
        )

        self.assertIsNone(contract.channel("roughness"))
        self.assertIsNone(contract.channel("metalness"))
        self.assertTrue(any(item.get("disposition") == "layer_only" for item in contract.unresolved))

    def test_sp_material_response_is_layer_only_not_global_pbr(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "crimson_material",
                "textures": {"material": "textures/cd_phm_02_blade_0014_sp.png"},
                "material_contract": {
                    "shader_family": "SkinnedMeshStandard_Ver2",
                    "texture_slots": {
                        "material": {
                            "parameter_name": "_grimeMaterialTextureR",
                            "shader_family": "SkinnedMeshStandard_Ver2",
                            "confidence": "authoritative",
                        }
                    },
                },
            }
        )

        self.assertIsNone(contract.channel("roughness"))
        self.assertIsNone(contract.channel("metalness"))
        self.assertTrue(any(item.get("disposition") == "layer_material_response" for item in contract.unresolved))

    def test_flow_hair_and_eye_maps_stay_unresolved_layer_diagnostics(self) -> None:
        cases = (
            ("_flowTexture", "textures/cd_phm_02_cloth_0014_flow.dds", "layer_flow"),
            ("_ssdmHairDirectionTexture", "textures/cd_phm_02_hair_0014_dir.dds", "layer_direction"),
            ("_irisTexture", "textures/cd_phm_02_eye_0014_iris.dds", "diagnostic_only"),
        )
        for parameter_name, source_path, disposition in cases:
            with self.subTest(parameter_name=parameter_name):
                contract = resolve_preview_batch_material_channels(
                    {
                        "material_name": "crimson_material",
                        "textures": {"material": source_path},
                        "material_contract": {
                            "shader_family": "SkinnedMeshStandard_Ver2",
                            "texture_slots": {
                                "material": {
                                    "parameter_name": parameter_name,
                                    "shader_family": "SkinnedMeshStandard_Ver2",
                                    "confidence": "authoritative",
                                    "layer_role": "layer",
                                    "layer_channel": "r",
                                    "blend_flags": ["role:layer", "channel:r"],
                                }
                            },
                        },
                    }
                )

                self.assertIsNone(contract.channel("roughness"))
                self.assertIsNone(contract.channel("metalness"))
                diagnostic = next(item for item in contract.unresolved if item.get("parameter_name") == parameter_name)
                self.assertEqual(disposition, diagnostic.get("disposition"))
                self.assertEqual("layer", diagnostic.get("slot"))
                self.assertIn("not", diagnostic.get("reason", ""))
                self.assertEqual("layer", diagnostic.get("layer_role"))
                self.assertEqual("r", diagnostic.get("layer_channel"))

    def test_parse_crimson_material_definition_records_parameters_and_groups(self) -> None:
        definition = parse_crimson_material_definition_text(
            """
            <Technique Name="SkinnedMeshStandard"/>
            <Permutation Name="MaterialType" Value="Cloth"/>
            <ParameterGroup Name="SkinnedMeshStandardParameterSet_Ver2"/>
            <Parameter Name="_materialTexture" Type="Texture2D" sRGB="False"/>
            <Parameter Name="_detailMaskTexture" Type="Texture2D" sRGB="False"/>
            """,
            source_path=r"C:\archive\skinnedmeshstandard_ver2.material",
        )

        self.assertEqual("SkinnedMeshStandard", definition.technique)
        self.assertEqual("Cloth", definition.permutations["MaterialType"])
        self.assertIn("_materialTexture", definition.parameters)
        self.assertEqual("False", definition.parameters["_detailMaskTexture"].srgb)
        self.assertIn("SkinnedMeshStandardParameterSet_Ver2", definition.parameter_groups)

    def test_exact_gltf_packed_material_promotes_roughness_and_metalness(self) -> None:
        contract = resolve_preview_batch_material_channels(
            {
                "material_name": "gltf_mr",
                "textures": {"material": "textures/mr.png"},
                "material_contract": {
                    "packed_channels": ["ao", "roughness", "metallic"],
                    "texture_slots": {"material": {"confidence": "exact"}},
                },
            }
        )

        self.assertEqual("g", contract.channel("roughness").source_channel)
        self.assertEqual("b", contract.channel("metalness").source_channel)
        self.assertEqual("packed_material", contract.channel("metalness").source_kind)
        self.assertFalse(contract.unresolved)


if __name__ == "__main__":
    unittest.main()
