from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_crimson_shader_corpus import main, scan_corpus


class ShaderCorpusAuditTests(unittest.TestCase):
    def test_scans_material_and_sidecar_xml_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            material = root / "skinnedmeshstandard_ver2.material"
            material.write_text(
                """
                <Technique Name="SkinnedMeshStandard_Ver2"/>
                <Parameter Name="_colorBlendingMaskTexture" Type="Texture2D" sRGB="False">
                    <ResourceReferencePath_ITexture value="character/texture/blade_ma.dds"/>
                </Parameter>
                <Parameter Name="_detailMaskTexture" Type="Texture2D" sRGB="False"/>
                """,
                encoding="utf-8",
            )
            sidecar = root / "weapon.pac_xml"
            sidecar.write_text(
                """
                <Material Name="Blade" ShaderFamily="SkinnedMeshStandard_Ver2">
                  <Parameter Name="_grimeMaterialTextureR" Type="Texture2D">
                    <ResourceReferencePath_ITexture value="character/texture/blade_sp.dds"/>
                  </Parameter>
                </Material>
                """,
                encoding="utf-8",
            )

            rows = scan_corpus([root])

        color_mask = next(row for row in rows if row["parameter_name"] == "_colorBlendingMaskTexture")
        self.assertEqual("standard_v2", color_mask["shader_family"])
        self.assertEqual("ma", color_mask["suffix"])
        self.assertEqual("authoritative", color_mask["authority"])
        self.assertEqual({"ao": "r", "roughness": "g", "metalness": "b"}, color_mask["promoted_channels"])
        detail = next(row for row in rows if row["parameter_name"] == "_detailMaskTexture")
        self.assertEqual("layer_only", detail["disposition"])
        grime = next(row for row in rows if row["parameter_name"] == "_grimeMaterialTextureR")
        self.assertEqual("r", grime["layer_channel"])
        self.assertEqual("layer_material_response", grime["disposition"])

    def test_cli_writes_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "test.material").write_text(
                '<Technique Name="SkinnedMeshStandard_Ver2"/><Parameter Name="_normalTexture" Type="Texture2D" sRGB="False"><ResourceReferencePath_ITexture value="body_n.dds"/></Parameter>',
                encoding="utf-8",
            )
            out_json = root / "audit.json"
            out_csv = root / "audit.csv"

            exit_code = main(["--roots", str(root), "--out-json", str(out_json), "--out-csv", str(out_csv)])

            self.assertEqual(0, exit_code)
            json_rows = json.loads(out_json.read_text(encoding="utf-8"))
            with out_csv.open("r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(1, len(json_rows))
            self.assertEqual(1, len(csv_rows))
            self.assertEqual("_normalTexture", json_rows[0]["parameter_name"])
            self.assertEqual("crimson_normal", json_rows[0]["source_kind"])


if __name__ == "__main__":
    unittest.main()
