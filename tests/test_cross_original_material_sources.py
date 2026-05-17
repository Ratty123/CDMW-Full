from types import SimpleNamespace
import unittest

from cdmw.modding.material_replacer import build_texture_replacement_payloads
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import (
    StaticDonorMaterialPlan,
    StaticDonorMaterialTextureBinding,
    StaticSubmeshMapping,
)


def _mesh(material: str = "target_horn") -> ParsedMesh:
    return ParsedMesh(
        path="character/model/target.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name=material,
                material=material,
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
            )
        ],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


def _target_sidecar_with_emissive() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="target_horn" ItemID="10">
  <Material _materialName="TargetShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/target_base.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_emissiveIntensityTexture" _name="_emissiveIntensityTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/target_emit.dds"/>
      </MaterialParameterTexture>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _target_sidecar_without_emissive() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="target_horn" ItemID="10">
  <Material _materialName="TargetShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/target_base.dds"/>
      </MaterialParameterTexture>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _donor_sidecar_with_emissive() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="donor_eye" ItemID="90">
  <Material _materialName="DonorEmissiveShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_emissiveIntensityTexture" _name="_emissiveIntensityTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/donor_eye_emit.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterFloat StringItemID="_emissivePower" _name="_emissivePower" Index="1" Value="6.0"/>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _target_sidecar_without_requested_wrapper() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="target_body" ItemID="11">
  <Material _materialName="BodyShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/target_body_base.dds"/>
      </MaterialParameterTexture>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


class CrossOriginalMaterialSourceTests(unittest.TestCase):
    def test_donor_texture_only_patches_target_parameter_without_wrapper_graft(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=_donor_sidecar_with_emissive(),
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            patch_mode="donor_textures",
            texture_bindings=[
                StaticDonorMaterialTextureBinding(
                    parameter_name="_emissiveIntensityTexture",
                    texture_path="character/texture/donor_eye_emit.dds",
                    slot_kind="base",
                    semantic_subtype="emissive",
                )
            ],
        )

        payloads, report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, _target_sidecar_with_emissive()),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual(1, len(payloads))
        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        patched = payloads[0].payload_data.decode("utf-8")
        self.assertIn('character/texture/donor_eye_emit.dds', patched)
        self.assertIn('_materialName="TargetShader"', patched)
        self.assertNotIn('DonorEmissiveShader', patched)
        self.assertFalse(any(payload.kind.startswith("texture") for payload in payloads))
        self.assertTrue(any("Donor texture binding patched" in warning for warning in report.warnings))

    def test_donor_material_behavior_uses_target_parameters_when_compatible(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=_donor_sidecar_with_emissive(),
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            donor_submesh_name="donor_eye",
            donor_shader_family="DonorEmissiveShader",
            patch_mode="material_behavior",
            texture_bindings=[
                StaticDonorMaterialTextureBinding(
                    parameter_name="_emissiveIntensityTexture",
                    texture_path="character/texture/donor_eye_emit.dds",
                    slot_kind="base",
                    semantic_subtype="emissive",
                )
            ],
        )

        payloads, report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, _target_sidecar_with_emissive()),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        patched = payloads[0].payload_data.decode("utf-8")
        self.assertIn('_materialName="TargetShader"', patched)
        self.assertNotIn('DonorEmissiveShader', patched)
        self.assertIn('character/texture/donor_eye_emit.dds', patched)
        self.assertTrue(any("target-compatible texture parameters" in warning for warning in report.warnings))

    def test_donor_material_behavior_grafts_emissive_wrapper_payload_but_preserves_target_identity(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=_donor_sidecar_with_emissive(),
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            donor_submesh_name="donor_eye",
            donor_shader_family="DonorEmissiveShader",
            patch_mode="material_behavior",
            texture_bindings=[
                StaticDonorMaterialTextureBinding(
                    parameter_name="_emissiveIntensityTexture",
                    texture_path="character/texture/donor_eye_emit.dds",
                    slot_kind="base",
                    semantic_subtype="emissive",
                )
            ],
        )

        payloads, report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, _target_sidecar_without_emissive()),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        patched = payloads[0].payload_data.decode("utf-8")
        self.assertIn('_subMeshName="target_horn"', patched)
        self.assertNotIn('_subMeshName="donor_eye"', patched)
        self.assertIn('DonorEmissiveShader', patched)
        self.assertIn('_emissivePower', patched)
        self.assertIn('character/texture/donor_eye_emit.dds', patched)
        self.assertTrue(any("Donor material behavior grafted" in warning for warning in report.warnings))

    def test_donor_material_profile_grafts_behavior_but_keeps_target_base_and_normal(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        target_sidecar = """
<SkinnedMeshMaterialWrapper _subMeshName="target_horn" ItemID="10">
  <Material _materialName="TargetShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/replacement_n.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/replacement_base.dds"/>
      </MaterialParameterTexture>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""
        donor_sidecar = """
<SkinnedMeshMaterialWrapper _subMeshName="donor_eye" ItemID="90">
  <Material _materialName="DonorStandardShader">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/donor_n.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/donor_base.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" _name="_colorBlendingMaskTexture" Index="2">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/donor_ma.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterBitFlag32 StringItemID="_colorBlendingFlag" _name="_colorBlendingFlag" _value="15" Index="3"/>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=donor_sidecar,
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            donor_submesh_name="donor_eye",
            donor_shader_family="DonorStandardShader",
            patch_mode="material_profile",
        )

        payloads, report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, target_sidecar),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        patched = payloads[0].payload_data.decode("utf-8")
        self.assertIn('_subMeshName="target_horn"', patched)
        self.assertNotIn('_subMeshName="donor_eye"', patched)
        self.assertIn("DonorStandardShader", patched)
        self.assertIn("character/texture/replacement_base.dds", patched)
        self.assertIn("character/texture/replacement_n.dds", patched)
        self.assertIn("character/texture/donor_ma.dds", patched)
        self.assertNotIn("character/texture/donor_base.dds", patched)
        self.assertNotIn("character/texture/donor_n.dds", patched)
        self.assertTrue(any("Donor material profile grafted" in warning for warning in report.warnings))

    def test_donor_original_dds_reference_stays_sidecar_only(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=_donor_sidecar_with_emissive(),
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            donor_submesh_name="donor_eye",
            patch_mode="material_behavior",
            texture_bindings=[
                StaticDonorMaterialTextureBinding(
                    parameter_name="_emissiveIntensityTexture",
                    texture_path="character/texture/donor_eye_emit.dds",
                    slot_kind="base",
                    semantic_subtype="emissive",
                )
            ],
        )

        payloads, _report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, _target_sidecar_with_emissive()),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        self.assertFalse(any(payload.kind in {"texture_generated", "texture_passthrough"} for payload in payloads))
        patched = payloads[0].payload_data.decode("utf-8")
        self.assertIn('character/texture/donor_eye_emit.dds', patched)

    def test_missing_target_wrapper_warns_and_blocks_unsafe_graft(self) -> None:
        target_entry = SimpleNamespace(path="character/model/target.pac_xml")
        plan = StaticDonorMaterialPlan(
            target_material_name="target_horn",
            donor_sidecar_path="character/model/donor.pac_xml",
            donor_sidecar_text=_donor_sidecar_with_emissive(),
            donor_sidecar_kind="pac_xml",
            donor_material_name="donor_eye",
            donor_submesh_name="donor_eye",
            patch_mode="material_behavior",
            texture_bindings=[
                StaticDonorMaterialTextureBinding(
                    parameter_name="_emissiveIntensityTexture",
                    texture_path="character/texture/donor_eye_emit.dds",
                    slot_kind="base",
                    semantic_subtype="emissive",
                )
            ],
        )

        payloads, report = build_texture_replacement_payloads(
            obj_mesh=_mesh(),
            rebuilt_mesh=_mesh(),
            texture_files=(),
            original_texture_refs=(),
            original_sidecars=((target_entry, _target_sidecar_without_requested_wrapper()),),
            submesh_mappings=[StaticSubmeshMapping(0, "target_horn", [0], 0)],
            texconv_path=None,
            read_original_texture_bytes=lambda _entry: b"",
            original_texture_source_path=lambda _entry: SimpleNamespace(),
            donor_material_plans=(plan,),
            pac_driven_sidecar=True,
        )

        self.assertEqual([], payloads)
        self.assertTrue(any("target wrapper was not found: target_horn" in warning for warning in report.warnings))


if __name__ == "__main__":
    unittest.main()
