from __future__ import annotations

import unittest

from cdmw.core.crimson_formats import (
    build_prefab_resource_path_patch,
    complete_swap_file_policy,
    decode_meshinfo,
    decode_paa_metabin,
    decode_prefab,
    parse_pami_material_instances,
)


def _lp(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


class CrimsonFormatDecodeTests(unittest.TestCase):
    def test_prefab_decode_and_same_length_resource_path_patch(self) -> None:
        old_path = "character/model/test_a.pac"
        new_path = "character/model/test_b.pac"
        payload = (
            b"\xff\xff\x04\x00"
            + _lp("_materialInstanceParameters")
            + _lp("_skinnedMeshFile")
            + _lp("ResourceReferencePath_SkinnedMesh")
            + _lp(old_path)
            + _lp("character/modelproperty/test_a.pac_xml")
        )

        decoded = decode_prefab(payload)
        self.assertIn("_materialInstanceParameters", decoded.declared_fields)
        self.assertTrue(decoded.material_parameter_markers)
        self.assertEqual(["model", "material_sidecar"], [reference.role for reference in decoded.references])
        self.assertIn("same-length", decoded.write_policy)

        patched = build_prefab_resource_path_patch(payload, {old_path: new_path})

        self.assertEqual(1, patched.patched_count)
        self.assertEqual(len(payload), len(patched.data))
        self.assertIn(new_path.encode("utf-8"), patched.data)
        self.assertNotIn(old_path.encode("utf-8"), patched.data)
        self.assertIn("exact-length", "\n".join(patched.proof_lines))

    def test_prefab_resource_path_patch_rejects_length_change(self) -> None:
        payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

        with self.assertRaises(ValueError):
            build_prefab_resource_path_patch(payload, {"character/model/test_a.pac": "character/model/much_longer_name.pac"})

    def test_meshinfo_decode_marks_material_context_read_only(self) -> None:
        payload = b"\xff\xff\x04\x00" + _lp("_boundingBoxMin") + _lp("_physicsMaterialName") + _lp("ResourceReferencePath_Animation")

        decoded = decode_meshinfo(payload)

        self.assertIn("_boundingBoxMin", decoded.declared_fields)
        self.assertIn("read-only", decoded.write_policy)
        self.assertIn("not a visible texture", decoded.material_policy)

    def test_pami_parse_flat_material_instance_parameters(self) -> None:
        text = """
<MaterialData>
  <StaticMesh Path="object/03_cube.pam"/>
  <Material PrimitiveName="03_cube.dds">
    <Common MaterialName="MultiTextured" TileType="Wall"/>
    <MaterialParameterTexture Name="_baseColorTexture" Value="/object/texture/cd_wall_mud_12.dds"/>
    <MaterialParameterTexture Name="_normalTexture" Value="object/texture/cd_wall_mud_12_n.dds"/>
    <MaterialParameterFloat Name="_brightness" Value="1.300000"/>
    <MaterialParameterColor Name="_tintColor" Value="0.878431 0.878431 0.878431"/>
  </Material>
</MaterialData>
"""

        instances = parse_pami_material_instances(text)

        self.assertEqual(1, len(instances))
        self.assertEqual("MultiTextured", instances[0].shader_name)
        self.assertEqual(
            [("_baseColorTexture", "object/texture/cd_wall_mud_12.dds"), ("_normalTexture", "object/texture/cd_wall_mud_12_n.dds")],
            [(parameter.parameter_name, parameter.texture_path) for parameter in instances[0].texture_parameters],
        )
        self.assertEqual("1.300000", instances[0].scalar_parameters["_brightness"])
        self.assertEqual("0.878431 0.878431 0.878431", instances[0].color_parameters["_tintColor"])

    def test_paa_metabin_decode_excludes_material_pipeline(self) -> None:
        decoded = decode_paa_metabin(b"\x00" * 24 + b"AnimationMetaData\x00" + _lp("character/animation/test.paa"))

        self.assertEqual("AnimationMetaData", decoded.declared_type)
        self.assertIn("animation metadata", decoded.write_policy)
        self.assertIn("excluded", decoded.material_policy)

    def test_complete_swap_file_policy_documents_authorities(self) -> None:
        self.assertIn("authoritative visible color", complete_swap_file_policy(".pami"))
        self.assertIn("relationship/placement", complete_swap_file_policy(".prefab"))
        self.assertIn("physics/bounds", complete_swap_file_policy(".meshinfo"))
        self.assertIn("excluded", complete_swap_file_policy(".paa_metabin"))


if __name__ == "__main__":
    unittest.main()
