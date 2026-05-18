import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import zipfile

from cdmw.modding.material_replacer import build_texture_replacement_payloads
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import (
    StaticDonorMaterialPlan,
    StaticDonorMaterialTextureBinding,
    StaticSubmeshMapping,
)
from cdmw.modding.working_mod_recipe import analyze_working_mod_package
from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.rendering.qtquick3d_preview_package import _input_texture_kind, _native_material_hints_for_batch


def _mesh() -> ParsedMesh:
    return ParsedMesh(
        path="character/model/target.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="target_blade",
                material="target_blade",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )


def _target_sidecar() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="target_blade">
  <Material _materialName="TargetShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_emissiveIntensityTexture" _name="_emissiveIntensityTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_emi.dds"/>
      </MaterialParameterTexture>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _sidecar(shader: str = "SkinnedMeshEmissive_Ver2", intensity: str = "5.5", texture: str = "character/texture/blade_emi.dds") -> str:
    return f"""
<SkinnedMeshMaterialWrapper _subMeshName="Blade">
  <Material _materialName="{shader}">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_n.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" _name="_colorBlendingMaskTexture" Index="2">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_ma.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_detailMaskTexture" _name="_detailMaskTexture" Index="3">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_mg.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_emissiveIntensityTexture" _name="_emissiveIntensityTexture" Index="4">
        <ResourceReferencePath_ITexture Name="_value" _path="{texture}"/>
      </MaterialParameterTexture>
      <MaterialParameterColor StringItemID="_emissiveColor" _name="_emissiveColor" Value="#00ccff"/>
      <MaterialParameterFloat StringItemID="_emissiveIntensity" _name="_emissiveIntensity" Value="{intensity}"/>
      <MaterialParameterColor StringItemID="_tintColorR" _name="_tintColorR" Value="#C49832FF"/>
      <MaterialParameterByte4 StringItemID="_dyeingPropertyBlend" _name="_dyeingPropertyBlend" Value="255"/>
      <MaterialParameterBitFlag32 StringItemID="_colorBlendingFlag" _name="_colorBlendingFlag" _value="15"/>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


class WorkingModMaterialRecipeTests(unittest.TestCase):
    def test_zip_analyzer_detects_crimsonforge_layout_emissive_recipe_and_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "Frostmourne.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("Frostmourne/manifest.json", json.dumps({"generated_by": "CrimsonForge"}))
                archive.writestr("Frostmourne/modinfo.json", json.dumps({"name": "Frostmourne"}))
                archive.writestr("Frostmourne/files/character/cd_phm_02_sword_0039.pac", b"PAC")
                archive.writestr("Frostmourne/files/character/cd_phm_02_sword_0039.pac_xml", _sidecar(intensity="3.0"))
                for name in ("blade.dds", "blade_n.dds", "blade_ma.dds", "blade_mg.dds", "blade_emi.dds"):
                    archive.writestr(f"Frostmourne/files/character/textures/{name}", b"DDS ")
                archive.writestr("Frostmourne/files/ui/itemicon_prefab_cd_phm_02_sword_0039.dds", b"DDS ")

            analysis = analyze_working_mod_package(archive_path)

            self.assertTrue(analysis.crimsonforge_like)
            self.assertEqual(1, len(analysis.pac_paths))
            self.assertEqual(1, len(analysis.icon_paths))
            recipe = analysis.recipes[0]
            self.assertEqual("SkinnedMeshEmissive_Ver2", recipe.shader_family)
            self.assertEqual("active", recipe.glow_status)
            self.assertTrue(recipe.glow_active)
            self.assertEqual(3.0, recipe.emissive_intensity)
            self.assertEqual("#00ccff", recipe.emissive_color)
            self.assertTrue(recipe.has_dedicated_emi_dds)
            self.assertIn("_emissiveIntensityTexture", {binding.parameter_name for binding in recipe.texture_bindings})
            self.assertIn("_colorBlendingMaskTexture", {binding.parameter_name for binding in recipe.texture_bindings})
            self.assertIn("_detailMaskTexture", {binding.parameter_name for binding in recipe.texture_bindings})

    def test_analyzer_distinguishes_glow_enabled_disabled_and_reused_emissive_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            enabled = root / "BladesNorse"
            disabled = root / "BladesNoGlow"
            reused = root / "Leviathan"
            for directory, intensity, texture in (
                (enabled, "5.5", "character/texture/blade_emi.dds"),
                (disabled, "0", "character/texture/blade_emi.dds"),
                (reused, "7.5", "character/texture/blade_ma.dds"),
            ):
                (directory / "files" / "character" / "textures").mkdir(parents=True)
                (directory / "files" / "character" / "weapon.pac_xml").write_text(
                    _sidecar(intensity=intensity, texture=texture),
                    encoding="utf-8",
                )
                (directory / "manifest.json").write_text("{}", encoding="utf-8")
                (directory / "modinfo.json").write_text("{}", encoding="utf-8")
                (directory / "files" / "character" / "textures" / Path(texture).name).write_bytes(b"DDS ")

            enabled_recipe = analyze_working_mod_package(enabled).recipes[0]
            disabled_recipe = analyze_working_mod_package(disabled).recipes[0]
            reused_recipe = analyze_working_mod_package(reused).recipes[0]

            self.assertEqual("active", enabled_recipe.glow_status)
            self.assertEqual("disabled", disabled_recipe.glow_status)
            self.assertFalse(disabled_recipe.glow_active)
            self.assertTrue(reused_recipe.glow_active)
            self.assertFalse(reused_recipe.has_dedicated_emi_dds)

    def test_donor_material_recipe_texture_sources_are_included_in_export_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            emissive_source = root / "blade_emi.dds"
            emissive_source.write_bytes(b"DDS emissive")
            target_entry = SimpleNamespace(path="character/modelproperty/target.pac_xml")
            plan = StaticDonorMaterialPlan(
                target_material_name="target_blade",
                donor_sidecar_path="character/modelproperty/donor.pac_xml",
                donor_sidecar_kind="pac_xml",
                patch_mode="donor_textures",
                texture_bindings=[
                    StaticDonorMaterialTextureBinding(
                        parameter_name="_emissiveIntensityTexture",
                        texture_path="character/texture/blade_emi.dds",
                        slot_kind="emissive",
                        semantic_subtype="emissive_intensity",
                        source_path=str(emissive_source),
                    )
                ],
            )

            payloads, report = build_texture_replacement_payloads(
                obj_mesh=_mesh(),
                rebuilt_mesh=_mesh(),
                texture_files=(),
                original_texture_refs=(),
                original_sidecars=((target_entry, _target_sidecar()),),
                submesh_mappings=[StaticSubmeshMapping(0, "target_blade", [0], 0)],
                texconv_path=None,
                read_original_texture_bytes=lambda _entry: b"",
                original_texture_source_path=lambda _entry: Path(),
                donor_material_plans=(plan,),
                pac_driven_sidecar=True,
            )

            by_kind = {payload.kind: payload for payload in payloads}
            self.assertIn("sidecar_generated", by_kind)
            self.assertIn("texture_donor_material", by_kind)
            self.assertEqual("character/texture/blade_emi.dds", by_kind["texture_donor_material"].target_path)
            self.assertIn("character/texture/blade_emi.dds", by_kind["sidecar_generated"].payload_data.decode("utf-8"))
            self.assertTrue(any("donor material recipe texture" in warning.lower() for warning in report.warnings))

    def test_preview_contract_treats_emissive_as_first_class_slot_and_hint(self) -> None:
        texture_input = PreviewMaterialTextureInput(
            slot_kind="emissive",
            parameter_name="_emissiveIntensityTexture",
            source_texture_path="character/texture/blade_emi.dds",
            preview_texture_path="C:/tmp/blade_emi.dds",
            semantic_type="emissive",
            semantic_subtype="emissive_intensity",
            shader_family="SkinnedMeshEmissive_Ver2",
            material_parameters=(
                PreviewMaterialParameterInput(parameter_name="_emissiveColor", value="#1A3C5FFF"),
                PreviewMaterialParameterInput(parameter_name="_emissiveIntensity", value="10.0", numeric_value=10.0),
            ),
        )
        batch = SimpleNamespace(preview_material_texture_inputs=(texture_input,))

        self.assertEqual("emissive", _input_texture_kind(texture_input))
        hints = _native_material_hints_for_batch(batch)
        self.assertTrue(hints["emissive_active"])
        self.assertEqual(10.0, hints["emissive_intensity"])
        self.assertEqual("#1A3C5FFF", hints["emissive_color"])


if __name__ == "__main__":
    unittest.main()
