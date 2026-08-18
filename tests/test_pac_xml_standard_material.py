"""Gates for the plain-material rewrite of a `.pac_xml` (`cdmw.core.pac_xml_standard_material`)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.pac_xml_standard_material import (  # noqa: E402
    EMISSIVE_SHADER,
    LAYERED_SHADER,
    STANDARD_SHADER,
    PacXmlMaterialError,
    PlainMaterial,
    find_material_wrappers,
    plain_material_xml,
    rewrite_materials,
)

TEX = "character/texture"


def texture(name: str, item_id: str, path: str, index: int, indent: str = "\t\t\t\t\t\t\t") -> str:
    return (
        f'{indent}<MaterialParameterTexture StringItemID="{name}" ItemID="{item_id}" _name="{name}" Index="{index}">\r\n'
        f'{indent}\t<ResourceReferencePath_ITexture Name="_value" _path="{path}"/>\r\n'
        f'{indent}</MaterialParameterTexture>\r\n'
    )


def wrapper(submesh: str, shader: str, params: str, item_id: int = 312) -> str:
    return (
        f'\t\t\t\t<SkinnedMeshMaterialWrapper ItemID="{item_id}" _subMeshName="{submesh}" _jiggleWindWeight="0">\r\n'
        f'\t\t\t\t\t<Material Name="_resourceMaterial" _materialName="{shader}">\r\n'
        f'\t\t\t\t\t\t<Vector Name="_permutations"/>\r\n'
        f'\t\t\t\t\t\t<Vector Name="_parameters">\r\n'
        f'{params}'
        f'\t\t\t\t\t\t</Vector>\r\n'
        f'\t\t\t\t\t</Material>\r\n'
        f'\t\t\t\t</SkinnedMeshMaterialWrapper>\r\n'
    )


# the shape the Builder writes: the template's layered material with the imported textures fitted in
IMPORTED = wrapper(
    "cd_phm_02_sword_0003", LAYERED_SHADER,
    '\t\t\t\t\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="6" Index="0"/>\r\n'
    + texture("_normalTexture", "6", f"{TEX}/cd_phm_02_sword_0003_lambert1_n.dds", 1)
    + texture("_baseColorTexture", "0", f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds", 2)
    + texture("_overlayColorTexture", "3936485985222654", f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds", 3)
    + texture("_detailMaskTexture", "2838988925698046", f"{TEX}/cd_phm_02_sword_0003_lambert1_material_mask_x_ma.dds", 4)
    + '\t\t\t\t\t\t\t<MaterialParameterColor StringItemID="_tintColorR" ItemID="1922282603675646" _name="_tintColorR" _value="#d8d8d8ff" Index="5"/>\r\n',
)
GLOWING = wrapper(
    "cd_phm_02_sword_handle_0003", LAYERED_SHADER,
    texture("_baseColorTexture", "0", f"{TEX}/cd_phm_02_sword_0003_gem_base_474747fcf8c5.dds", 0)
    + texture("_detailMaskTexture", "2838988925698046", f"{TEX}/cd_phm_02_sword_0003_gem_detail_mask_neutral_ma.dds", 1)
    + texture("_emissiveIntensityTexture", "1638159983050750", f"{TEX}/cd_phm_02_sword_0003_gem_emissive_emi.dds", 2)
    + '\t\t\t\t\t\t\t<MaterialParameterColor StringItemID="_emissiveColor" ItemID="2065176433000446" _name="_emissiveColor" _value="#00FFCAFF" Index="3"/>\r\n'
    + '\t\t\t\t\t\t\t<MaterialParameterFloat StringItemID="_emissiveIntensity" ItemID="3419583792807934" _name="_emissiveIntensity" _value="10.000000" Index="4"/>\r\n',
    item_id=313,
)
# a wrapper the import did not touch: the template's own layered material
TEMPLATE = wrapper(
    "cd_phm_02_sword_guard_0003", LAYERED_SHADER,
    texture("_normalTexture", "1", f"{TEX}/cd_phm_02_guard_0003_n.dds", 0)
    + texture("_colorBlendingMaskTexture", "3936485985222654", f"{TEX}/cd_temp_r_m.dds", 1)
    + texture("_detailMaskTexture", "2838988925698046", f"{TEX}/cd_phm_02_guard_0003_mg.dds", 2),
    item_id=314,
)
HEAD = (
    '\ufeff<SkinnedMeshPropertyCommon ReflectObjectXMLDataVersion="9"/>\r\n<ModelPropertyList>\r\n'
    '\t<ModelProperty Index="0" Version="Reflection">\r\n\t\t<SkinnedMeshProperty ReflectObjectXMLDataVersion="9">\r\n'
    '\t\t\t<Vector Name="_subMeshResources" IdBase="315" isOverrided="true">\r\n'
)
TAIL = '\t\t\t</Vector>\r\n\t\t</SkinnedMeshProperty>\r\n\t</ModelProperty>\r\n</ModelPropertyList>\r\n'
SIDECAR = HEAD + IMPORTED + GLOWING + TEMPLATE + TAIL


class FindWrappersTests(unittest.TestCase):
    def test_reads_every_wrapper_with_its_textures_and_values(self) -> None:
        wrappers = find_material_wrappers(SIDECAR)
        self.assertEqual([w.submesh_name for w in wrappers], ["cd_phm_02_sword_0003", "cd_phm_02_sword_handle_0003", "cd_phm_02_sword_guard_0003"])
        self.assertEqual({w.shader for w in wrappers}, {LAYERED_SHADER})
        first = wrappers[0]
        self.assertEqual(first.textures["_baseColorTexture"], f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds")
        self.assertEqual(first.textures["_normalTexture"], f"{TEX}/cd_phm_02_sword_0003_lambert1_n.dds")
        self.assertEqual(first.value("_renderSettingFlag"), "6")
        self.assertEqual(first.value("_tintColorR"), "#d8d8d8ff")
        self.assertIsNone(first.value("_emissiveColor"))
        self.assertEqual([p.index for p in first.parameters], [0, 1, 2, 3, 4, 5])
        glowing = wrappers[1]
        self.assertEqual((glowing.value("_emissiveColor"), glowing.value("_emissiveIntensity")), ("#00FFCAFF", "10.000000"))
        # the span covers the whole <Material> block, indentation included
        block = SIDECAR[first.start:first.end]
        self.assertTrue(block.startswith("\t\t\t\t\t<Material Name=") and block.endswith("</Material>"), block[:60])
        self.assertEqual(first.indent, "\t\t\t\t\t")
        self.assertEqual(find_material_wrappers("<nothing/>"), ())


class PlainMaterialXmlTests(unittest.TestCase):
    def test_standard_material_takes_the_shipped_countdown_ids(self) -> None:
        text = plain_material_xml(PlainMaterial(base="a.dds", normal="a_n.dds", material="a_sp.dds"), indent="\t", newline="\n")
        self.assertIn(f'_materialName="{STANDARD_SHADER}"', text)
        params = re.findall(r'StringItemID="(\w+)" ItemID="(\d+)" _name="\w+" Index="(\d+)"', text)
        # the most common shipped pattern for this set (984 files): base 2, normal 1, material 0
        self.assertEqual(params, [("_baseColorTexture", "2", "0"), ("_normalTexture", "1", "1"), ("_materialTexture", "0", "2")])
        self.assertIn('<ResourceReferencePath_ITexture Name="_value" _path="a_sp.dds"/>', text)
        self.assertNotIn("_renderSettingFlag", text)
        self.assertNotIn("_emissive", text)
        self.assertTrue(text.startswith('\t<Material Name="_resourceMaterial"') and text.endswith("\t</Material>"))
        self.assertIn('\t\t<Vector Name="_permutations"/>\n\t\t<Vector Name="_parameters">', text)
        # with a render flag the flag takes 0 and the textures count down above it (the dart pattern)
        flagged = plain_material_xml(PlainMaterial(base="a.dds", normal="a_n.dds", material="a_sp.dds", render_flag=4))
        self.assertEqual(
            re.findall(r'StringItemID="(\w+)" ItemID="(\d+)"', flagged),
            [("_baseColorTexture", "3"), ("_normalTexture", "2"), ("_materialTexture", "1"), ("_renderSettingFlag", "0")],
        )
        self.assertIn('_name="_renderSettingFlag" _value="4" Index="3"', flagged)
        base_only = plain_material_xml(PlainMaterial(base="a.dds"))
        self.assertEqual(re.findall(r'StringItemID="(\w+)" ItemID="(\d+)"', base_only), [("_baseColorTexture", "0")])
        with self.assertRaisesRegex(PacXmlMaterialError, "base colour"):
            plain_material_xml(PlainMaterial(base=""))

    def test_emissive_material_carries_the_shipped_hashed_ids(self) -> None:
        text = plain_material_xml(PlainMaterial(base="a.dds", material="a_sp.dds", emissive_texture="a_emi.dds", emissive_color="#4461F3FF", emissive_intensity=4.5))
        self.assertIn(f'_materialName="{EMISSIVE_SHADER}"', text)
        params = re.findall(r'StringItemID="(\w+)" ItemID="(\d+)" _name="\w+"(?: _value="([^"]*)")? Index="(\d+)"', text)
        self.assertEqual(params, [
            ("_baseColorTexture", "1", "", "0"),
            ("_materialTexture", "0", "", "1"),
            ("_emissiveIntensityTexture", "1638159983050750", "", "2"),
            ("_emissiveColor", "2065176433000446", "#4461F3FF", "3"),
            ("_emissiveIntensity", "3419583792807934", "4.500000", "4"),
        ])
        self.assertIn('<MaterialParameterColor StringItemID="_emissiveColor"', text)
        self.assertIn('<MaterialParameterFloat StringItemID="_emissiveIntensity"', text)


class RewriteTests(unittest.TestCase):
    def test_rewrites_the_named_wrappers_and_keeps_the_rest_byte_for_byte(self) -> None:
        result = rewrite_materials(SIDECAR, {
            "cd_phm_02_sword_0003": PlainMaterial(
                base=f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds", normal=f"{TEX}/cd_phm_02_sword_0003_lambert1_n.dds",
                material=f"{TEX}/cd_phm_02_sword_0003_lambert1_sp.dds",
            ),
            "CD_PHM_02_SWORD_HANDLE_0003": PlainMaterial(
                base=f"{TEX}/cd_phm_02_sword_0003_gem_base_474747fcf8c5.dds", material=f"{TEX}/cd_phm_02_sword_0003_gem_detail_mask_neutral_ma.dds",
                emissive_texture=f"{TEX}/cd_phm_02_sword_0003_gem_emissive_emi.dds", emissive_color="#00FFCAFF", emissive_intensity=10.0,
            ),
            "not_in_the_file": PlainMaterial(base="x.dds"),
        })
        self.assertEqual(result.rewritten, ("cd_phm_02_sword_0003", "cd_phm_02_sword_handle_0003"))
        self.assertEqual(result.missing, ("not_in_the_file",))
        text = result.text
        self.assertTrue(text.startswith(HEAD), "the head is untouched")
        self.assertTrue(text.endswith(TAIL))
        self.assertIn(TEMPLATE, text, "the template's own wrapper is byte for byte")
        after = find_material_wrappers(text)
        self.assertEqual([(w.submesh_name, w.shader) for w in after], [
            ("cd_phm_02_sword_0003", STANDARD_SHADER), ("cd_phm_02_sword_handle_0003", EMISSIVE_SHADER), ("cd_phm_02_sword_guard_0003", LAYERED_SHADER),
        ])
        self.assertEqual([p.name for p in after[0].parameters], ["_baseColorTexture", "_normalTexture", "_materialTexture"])
        self.assertEqual(after[0].textures["_materialTexture"], f"{TEX}/cd_phm_02_sword_0003_lambert1_sp.dds")
        self.assertNotIn("_overlayColorTexture", text)
        self.assertNotIn("_tintColorR", text)
        self.assertNotIn("_detailMaskTexture", text[: text.index("cd_phm_02_sword_guard_0003")], "the imported wrappers lost the layer slots")
        # wrapper attributes and the file's CRLF and tab conventions survive
        self.assertIn('<SkinnedMeshMaterialWrapper ItemID="312" _subMeshName="cd_phm_02_sword_0003" _jiggleWindWeight="0">', text)
        self.assertNotIn("\n\n", text)
        self.assertEqual(text.count("\r\n"), text.count("\n"), "every newline is CRLF, as the file's were")
        self.assertIn('\r\n\t\t\t\t\t<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard">\r\n\t\t\t\t\t\t<Vector Name="_permutations"/>', text)
        # rewriting is stable: doing it again changes nothing
        again = rewrite_materials(text, {"cd_phm_02_sword_0003": PlainMaterial(
            base=f"{TEX}/cd_phm_02_sword_0003_lambert1_basecolor.dds", normal=f"{TEX}/cd_phm_02_sword_0003_lambert1_n.dds",
            material=f"{TEX}/cd_phm_02_sword_0003_lambert1_sp.dds",
        )})
        self.assertEqual(again.text, text)

    def test_lf_files_stay_lf_and_empty_files_are_refused(self) -> None:
        lf = SIDECAR.replace("\r\n", "\n")
        result = rewrite_materials(lf, {"cd_phm_02_sword_0003": PlainMaterial(base="a.dds")})
        self.assertNotIn("\r", result.text)
        self.assertEqual(find_material_wrappers(result.text)[0].textures, {"_baseColorTexture": "a.dds"})
        with self.assertRaisesRegex(PacXmlMaterialError, "no material wrappers"):
            rewrite_materials("<ModelPropertyList/>", {"x": PlainMaterial(base="a.dds")})


if __name__ == "__main__":
    unittest.main()
