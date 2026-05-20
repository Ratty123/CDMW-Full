from pathlib import Path
import unittest

from cdmw.core.upscale_profiles import (
    classify_texture_type,
    derive_texture_group_key,
    infer_texture_semantics,
    suggest_texture_upscale_decision,
)


class TextureSemanticPathTests(unittest.TestCase):
    def test_texture_semantic_helpers_accept_path_objects(self) -> None:
        texture_path = Path("character/texture/Imported_Normal_GreenUp.dds")

        self.assertEqual(classify_texture_type(texture_path), "normal")
        self.assertEqual(derive_texture_group_key(texture_path), "character/texture/Imported")
        self.assertEqual(
            derive_texture_group_key(Path("character/texture/Imported_Base_Color.dds")),
            "character/texture/Imported",
        )

        semantic = infer_texture_semantics(texture_path)
        self.assertEqual(semantic.path, "character/texture/Imported_Normal_GreenUp.dds")
        self.assertEqual(semantic.texture_type, "normal")

        decision = suggest_texture_upscale_decision(texture_path)
        self.assertEqual(decision.texture_type, "normal")

    def test_technique_files_are_treated_as_material_sidecars(self) -> None:
        self.assertEqual(classify_texture_type("technique/character.technique"), "sidecar")

    def test_rgb_texture_sidecar_parameter_is_layer_blend_mask(self) -> None:
        sidecar = (
            '<MaterialParameterTexture _name="_rgbTexture" '
            'Value="object/texture/cd_wall_rgb.dds" />'
        )
        semantic = infer_texture_semantics(
            "object/texture/cd_wall_rgb.dds",
            sidecar_texts=(sidecar,),
        )

        self.assertEqual("mask", semantic.texture_type)
        self.assertEqual("layer_blend_mask", semantic.semantic_subtype)
        self.assertIn("layer_g", semantic.packed_channels)


if __name__ == "__main__":
    unittest.main()
