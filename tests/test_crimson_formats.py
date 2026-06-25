from __future__ import annotations

import unittest

from cdmw.core.crimson_formats import (
    build_prefab_resource_path_patch,
    complete_swap_file_policy,
    decode_meshinfo,
    decode_paa_metabin,
    decode_prefab,
    parse_pami_material_instances,
    rebuild_prefab_no_edit,
    rebuild_prefab_resized_strings,
    rebuild_prefab_same_length_strings,
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
            + _lp("_worldTransform")
            + _lp("Transform")
            + b"\x01\x00\x10\x00\x00\x00\x00\x00"
            + _lp(old_path)
            + _lp("character/modelproperty/test_a.pac_xml")
        )

        decoded = decode_prefab(payload)
        self.assertEqual(0xFFFF, decoded.header.magic)
        self.assertEqual(4, decoded.header.version)
        self.assertEqual(4, decoded.header.first_string_offset)
        self.assertTrue(decoded.layout.fully_accounted)
        self.assertEqual(len(payload), decoded.layout.accounted_byte_count)
        self.assertGreater(decoded.layout.preserved_byte_count, 0)
        self.assertGreater(decoded.layout.string_span_count, 0)
        self.assertIn("_materialInstanceParameters", decoded.declared_fields)
        self.assertIn(
            ("_skinnedMeshFile", "ResourceReferencePath_SkinnedMesh"),
            [(member.name, member.type_name) for member in decoded.member_declarations],
        )
        members = {member.name: member for member in decoded.member_declarations}
        self.assertTrue(members["_skinnedMeshFile"].is_reference)
        self.assertEqual("reference", members["_skinnedMeshFile"].descriptor_kind)
        self.assertTrue(members["_worldTransform"].is_transform)
        self.assertEqual("transform", members["_worldTransform"].descriptor_kind)
        self.assertEqual((1, 16, 0, 0), members["_worldTransform"].descriptor_words_le_u16)
        self.assertEqual(0, members["_worldTransform"].array_stride_hint)
        self.assertEqual(0, members["_worldTransform"].array_count_hint)
        self.assertTrue(decoded.material_parameter_markers)
        self.assertEqual(["model", "material_sidecar"], [reference.role for reference in decoded.references])
        self.assertIn("same-length", decoded.write_policy)
        self.assertEqual(payload, rebuild_prefab_no_edit(payload))
        self.assertIn(new_path.encode("utf-8"), rebuild_prefab_same_length_strings(payload, {5: new_path}))

        patched = build_prefab_resource_path_patch(payload, {old_path: new_path})

        self.assertEqual(1, patched.patched_count)
        self.assertEqual(len(payload), len(patched.data))
        self.assertIn(new_path.encode("utf-8"), patched.data)
        self.assertNotIn(old_path.encode("utf-8"), patched.data)
        proof = "\n".join(patched.proof_lines)
        self.assertIn("exact-length", proof)
        self.assertIn("layout encoder", proof)

    def test_prefab_same_length_string_rebuild_rejects_resize(self) -> None:
        payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

        with self.assertRaises(ValueError):
            rebuild_prefab_same_length_strings(payload, {0: "character/model/much_longer_name.pac"})

    def test_prefab_resized_string_rebuild_updates_offset_candidates(self) -> None:
        old_path = "character/model/a.pac"
        new_path = "character/model/longer_a.pac"
        first = b"\xff\xff\x04\x00" + _lp(old_path)
        target_offset = len(first) + 4
        payload = first + target_offset.to_bytes(4, "little") + _lp("character/model/b.pac")
        delta = len(new_path.encode("utf-8")) - len(old_path.encode("utf-8"))

        patched = rebuild_prefab_resized_strings(payload, {0: new_path})

        candidate_offset = len(b"\xff\xff\x04\x00" + _lp(new_path))
        self.assertEqual(target_offset + delta, int.from_bytes(patched[candidate_offset : candidate_offset + 4], "little"))
        self.assertIn(new_path.encode("utf-8"), patched)
        self.assertIn(b"character/model/b.pac", patched)
        self.assertEqual(patched, rebuild_prefab_no_edit(patched))

    def test_prefab_resized_string_rebuild_applies_cumulative_deltas(self) -> None:
        old_a = "character/model/a.pac"
        old_b = "character/model/b.pac"
        new_a = "character/model/longer_a.pac"
        new_b = "character/model/longer_b.pac"
        prefix = b"\xff\xff\x04\x00" + _lp(old_a)
        marker_a_offset = len(prefix)
        second_offset = marker_a_offset + 4
        middle = second_offset.to_bytes(4, "little") + _lp(old_b)
        marker_b_offset = len(prefix) + len(middle)
        payload = prefix + middle + marker_b_offset.to_bytes(4, "little") + b"\x99\x88"
        delta_a = len(new_a.encode("utf-8")) - len(old_a.encode("utf-8"))
        delta_b = len(new_b.encode("utf-8")) - len(old_b.encode("utf-8"))

        patched = rebuild_prefab_resized_strings(payload, {0: new_a, 1: new_b})

        patched_marker_a_offset = len(b"\xff\xff\x04\x00" + _lp(new_a))
        patched_marker_b_offset = patched_marker_a_offset + 4 + len(_lp(new_b))
        self.assertEqual(second_offset + delta_a, int.from_bytes(patched[patched_marker_a_offset : patched_marker_a_offset + 4], "little"))
        self.assertEqual(
            marker_b_offset + delta_a + delta_b,
            int.from_bytes(patched[patched_marker_b_offset : patched_marker_b_offset + 4], "little"),
        )
        self.assertIn(new_a.encode("utf-8"), patched)
        self.assertIn(new_b.encode("utf-8"), patched)
        self.assertEqual(patched, rebuild_prefab_no_edit(patched))

    def test_prefab_resized_string_rebuild_rejects_overlapping_offset_candidates(self) -> None:
        old_path = "character/model/a.pac"
        payload = bytearray(b"\x00" * 16653)
        payload[0:4] = b"\xff\xff\x04\x00"
        payload[4 : 4 + len(_lp(old_path))] = _lp(old_path)
        payload[40:45] = bytes((0xE5, 0x40, 0, 0, 0))
        payload[60 : 60 + len(_lp("IndexedStringA"))] = _lp("IndexedStringA")
        target = "tree/tree_pine_spruce_norway_hero_03.pat"
        payload[16609 : 16609 + len(_lp(target))] = _lp(target)

        with self.assertRaisesRegex(ValueError, "offset candidates overlap"):
            rebuild_prefab_resized_strings(bytes(payload), {0: "character/model/longer_a.pac"})

    def test_prefab_decode_reports_offset_candidates_in_preserved_bytes(self) -> None:
        prefix = b"\xff\xff\x04\x00" + _lp("_target") + _lp("IndexedStringA")
        target_offset = len(prefix) + 4
        payload = prefix + target_offset.to_bytes(4, "little") + _lp("character/model/test_a.pac")

        decoded = decode_prefab(payload)

        self.assertEqual(1, len(decoded.offset_candidates))
        self.assertEqual(target_offset, decoded.offset_candidates[0].value)
        self.assertEqual("string_length_prefix", decoded.offset_candidates[0].target_kind)

    def test_prefab_decode_marks_list_descriptor_members_as_arrays(self) -> None:
        payload = (
            b"\xff\xff\x04\x00"
            + _lp("_socketList")
            + _lp("ReflectObjectPtr")
            + b"\x07\x00\x00\x00\x08\x10\x00\x01"
            + _lp("character/model/test_a.pac")
        )

        member = decode_prefab(payload).member_declarations[0]

        self.assertEqual("array", member.descriptor_kind)
        self.assertTrue(member.is_array)
        self.assertTrue(member.is_reference)
        self.assertEqual(0, member.array_stride_hint)
        self.assertEqual(256, member.array_count_hint)

    def test_prefab_decode_does_not_mark_bool_transform_names_as_transform_values(self) -> None:
        payload = (
            b"\xff\xff\x04\x00"
            + _lp("_applyTransform")
            + _lp("bool")
            + b"\x00\x00\x01\x00\x00\x00\x00\x00"
            + _lp("character/model/test_a.pac")
        )

        member = decode_prefab(payload).member_declarations[0]

        self.assertEqual("bool", member.descriptor_kind)
        self.assertFalse(member.is_transform)

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
