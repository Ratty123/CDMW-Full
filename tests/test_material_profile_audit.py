from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_crimson_material_profiles import (
    build_summary,
    iter_material_profile_rows,
    iter_pso_profile_rows,
    main,
)


class MaterialProfileAuditTests(unittest.TestCase):
    def test_audits_material_texture_parameters_and_pso_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "standard.material").write_text(
                """
                <Technique Name="SkinnedMeshStandard_Ver2"/>
                <Permutation Name="AlphaTest" Value="False"/>
                <Parameter Name="_colorBlendingMaskTexture" Type="Texture" sRGB="False" DefaultValue="texture/body_ma.dds"/>
                <Parameter Name="_detailNormalMaskR" Type="Texture" sRGB="False" DefaultValue="texture/layer_n.dds"/>
                """,
                encoding="utf-8",
            )
            (root / "pso_to_precompile.xml").write_text(
                """
                <PSOCreateInfoList>
                  <PSOCreateInfo>
                    <RenderPassName>CharacterGBuffer</RenderPassName>
                    <PipelineMarker>CharacterGBuffer_SkinnedMeshStandard_Ver2_at1_da1_gfmd</PipelineMarker>
                    <MaterialName>SkinnedMeshStandard_Ver2</MaterialName>
                  </PSOCreateInfo>
                </PSOCreateInfoList>
                """,
                encoding="utf-8",
            )

            material_rows = iter_material_profile_rows([root])
            pso_rows = iter_pso_profile_rows([root])
            summary = build_summary(material_rows, pso_rows)

        self.assertEqual(2, len(material_rows))
        self.assertEqual("crimson_color_blending_mask", material_rows[0]["source_kind"])
        self.assertEqual("crimson_layer_normal", material_rows[1]["source_kind"])
        self.assertEqual(1, len(pso_rows))
        self.assertEqual(("at1", "da1", "gfmd"), pso_rows[0]["permutation_flags"])
        self.assertEqual(2, summary["material_profile_rows"])

    def test_cli_writes_summary_and_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "standard.material").write_text(
                '<Technique Name="SkinnedMeshStandard_Ver2"/><Parameter Name="_normalTexture" Type="Texture" DefaultValue="body_n.dds"/>',
                encoding="utf-8",
            )
            out_json = root / "profiles.json"
            out_material = root / "profiles.csv"
            out_pso = root / "pso.csv"

            exit_code = main(
                [
                    "--roots",
                    str(root),
                    "--out-json",
                    str(out_json),
                    "--out-material-csv",
                    str(out_material),
                    "--out-pso-csv",
                    str(out_pso),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(1, json.loads(out_json.read_text(encoding="utf-8"))["material_profile_rows"])
            self.assertTrue(out_material.is_file())
            self.assertTrue(out_pso.is_file())


if __name__ == "__main__":
    unittest.main()
