from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_pac_xml_material_authority import (
    build_pac_xml_material_authority_audit_summary,
    default_pac_xml_material_authority_roots,
    iter_pac_xml_material_authority_reports,
    main,
)


class PacXmlMaterialAuthorityAuditTests(unittest.TestCase):
    def test_audit_summarizes_inherited_and_unknown_material_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = root / "character/modelproperty/weapon/blade.pac_xml"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0203.dds"/></MaterialParameterTexture>'
                '<MaterialParameterFloat _name="_wetnessBoost" _value="0.250000"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )

            reports = iter_pac_xml_material_authority_reports([root], authority_contract="true_source_authority")
            summary = build_pac_xml_material_authority_audit_summary(reports)

        self.assertEqual(1, summary["source_files"])
        self.assertEqual([("needs_review", 1)], summary["status_counts"])
        self.assertIn(("shared_texturelayer", 1), summary["inherited_influence_reasons"])
        self.assertIn(("replace_with_source_owned_texture_or_neutral_default", 1), summary["neutralization_actions"])
        self.assertIn(("required", 1), summary["neutralization_statuses"])
        self.assertIn(("_wetnessBoost", 1), summary["unknown_material_response_parameters"])
        self.assertEqual(1, len(summary["unknown_material_response_examples"]))
        unknown = summary["unknown_material_response_examples"][0]
        self.assertEqual("character/modelproperty/weapon/blade.pac_xml", unknown["source_file"])
        self.assertEqual("Blade", unknown["wrapper_name"])
        self.assertEqual("_wetnessBoost", unknown["parameter_name"])
        self.assertEqual("unknown_scalar_or_color_response", unknown["reason"])
        self.assertIn("reports", summary)

    def test_audit_summary_exposes_corpus_abi_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = root / "blade.pac_xml"
            sidecar.write_text(
                '<Root><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="1190">'
                '<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Blade">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="6" Index="0"/>'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="9" _name="_overlayColorTexture" Index="1">'
                '<ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterColor StringItemID="_tintColorR" ItemID="10" _name="_tintColorR" _value="#402c1aff" Index="2"/>'
                '<MaterialParameterFloat StringItemID="_wetnessBoost" ItemID="11" _name="_wetnessBoost" _value="0.250000" Index="3"/>'
                '<MaterialParameterBool StringItemID="_alphaTest" ItemID="12" _name="_alphaTest" _value="1" Index="4"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Vector></SkinnedMeshProperty></Root>",
                encoding="utf-8",
            )

            reports = iter_pac_xml_material_authority_reports([root], authority_contract="true_source_authority")
            summary = build_pac_xml_material_authority_audit_summary(reports)

        evidence = summary["abi_evidence"]
        self.assertEqual(1, evidence["wrapper_rows"])
        self.assertEqual(1, evidence["submesh_binding_rows"])
        self.assertEqual(5, evidence["parameter_rows"])
        self.assertEqual(2, evidence["runtime_abi_parameter_rows"])
        self.assertEqual(1, evidence["source_authority_parameter_rows"])
        self.assertEqual(1, evidence["inherited_influence_parameter_rows"])
        self.assertEqual(1, evidence["unknown_material_response_parameter_rows"])
        self.assertEqual(1, evidence["neutralization_action_rows"])
        self.assertEqual(1, evidence["neutralization_required_rows"])
        self.assertEqual(1, evidence["texture_parameter_rows"])
        self.assertEqual(3, evidence["scalar_range_rows"])
        self.assertEqual(1, evidence["color_parameter_rows"])
        self.assertEqual(1, evidence["alpha_control_rows"])
        self.assertEqual(1, evidence["wrapper_item_id_rows"])
        self.assertEqual(1, evidence["submesh_item_id_rows"])
        self.assertEqual(1, evidence["submesh_id_base_rows"])
        self.assertEqual(5, evidence["parameter_item_id_rows"])
        self.assertEqual(5, evidence["parameter_index_rows"])
        self.assertIn(("Blade", 1), summary["wrapper_names"])
        self.assertIn(("Blade", 1), summary["submesh_binding_names"])
        self.assertIn(("Texture", 1), summary["parameter_types"])
        self.assertIn(("_overlayColorTexture", 1), summary["texture_parameter_names"])
        self.assertIn(("base", 1), summary["texture_roles"])
        self.assertIn(("alpha_test", 1), summary["alpha_control_modes"])
        self.assertIn(("_tintColorR", 1), summary["color_parameter_names"])
        self.assertIn(("_renderSettingFlag", 1), summary["runtime_abi_parameters"])
        self.assertIn(("_overlayColorTexture", 1), summary["source_authority_parameters"])
        self.assertIn(("_tintColorR", 1), summary["inherited_influence_parameters"])
        self.assertIn(("_wetnessBoost", 1), summary["unknown_material_response_parameters"])
        self.assertIn(("tint_color", 1), summary["inherited_influence_reasons"])
        self.assertIn(("neutralize_scalar_or_color_to_source_neutral_default", 1), summary["neutralization_actions"])
        self.assertEqual("cdmw_pac_xml_material_authority_audit_v1", json.loads(json.dumps(summary))["schema"])

    def test_default_roots_prefer_tmp_shader_corpus_before_game_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local = root / ".tmp_crimson_shader_corpus"
            game = root / "Crimson Desert"
            local.mkdir()
            game.mkdir()
            (local / "local.pac_xml").write_text("<Root />", encoding="utf-8")
            (game / "game.pac_xml").write_text("<Root />", encoding="utf-8")

            roots = default_pac_xml_material_authority_roots(repo_root=root, game_root=game)

        self.assertEqual((local,), roots)

    def test_default_roots_use_game_only_when_tmp_corpus_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local = root / ".tmp_crimson_shader_corpus"
            game = root / "Crimson Desert"
            local.mkdir()
            game.mkdir()
            (game / "game.pac_xml").write_text("<Root />", encoding="utf-8")

            roots = default_pac_xml_material_authority_roots(repo_root=root, game_root=game)

        self.assertEqual((game,), roots)

    def test_cli_writes_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = root / "blade.pac_xml"
            sidecar.write_text(
                '<Root><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="1190">'
                '<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Blade">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="9" _name="_overlayColorTexture" Index="1">'
                '<ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterColor StringItemID="_tintColorR" ItemID="10" _name="_tintColorR" _value="#402c1aff" Index="2"/>'
                '<MaterialParameterFloat StringItemID="_alphaCutoff" ItemID="37" _name="_alphaCutoff" _value="0.420000" Index="11"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Vector></SkinnedMeshProperty></Root>",
                encoding="utf-8",
            )
            out_json = root / "authority.json"
            out_csv = root / "authority.csv"

            exit_code = main(
                [
                    "--roots",
                    str(root),
                    "--out-json",
                    str(out_json),
                    "--out-csv",
                    str(out_csv),
                    "--authority-contract",
                    "runtime_xml_preserve",
                ]
            )

            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertEqual("cdmw_pac_xml_material_authority_audit_v1", data["schema"])
            self.assertEqual(1, data["source_files"])
            self.assertTrue(out_csv.is_file())
            with out_csv.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows_by_name = {row["parameter_name"]: row for row in rows}
            overlay = rows_by_name["_overlayColorTexture"]
            tint = rows_by_name["_tintColorR"]
            alpha_cutoff = rows_by_name["_alphaCutoff"]
            self.assertEqual("runtime_xml_preserve", overlay["authority_contract"])
            self.assertEqual("0", overlay["wrapper_order"])
            self.assertEqual("1191", overlay["wrapper_item_id"])
            self.assertEqual("0", overlay["submesh_order"])
            self.assertEqual("1191", overlay["submesh_item_id"])
            self.assertEqual("1190", overlay["submesh_id_base"])
            self.assertEqual("9", overlay["item_id"])
            self.assertEqual("1", overlay["index"])
            self.assertEqual("base", overlay["role"])
            self.assertEqual("#402c1aff", tint["value"])
            self.assertEqual("64,44,26,255", tint["color_rgba"])
            self.assertEqual("rgba", tint["color_order"])
            self.assertEqual("0.42", alpha_cutoff["numeric_value"])
            self.assertEqual("alpha_cutout", alpha_cutoff["alpha_mode"])


if __name__ == "__main__":
    unittest.main()
