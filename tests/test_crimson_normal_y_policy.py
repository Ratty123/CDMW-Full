from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools.report_crimson_normal_y_policy import build_normal_y_policy_report, main


class CrimsonNormalYPolicyTests(unittest.TestCase):
    def test_infers_green_up_policy_from_audit_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audit = root / "audit.csv"
            archive = root / "archive.py"
            helper = root / "main.cpp"
            d3d11 = root / "d3d11.cpp"
            with audit.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["slot", "source_kind", "parameter_name", "dds_path", "suffix", "authority"])
                writer.writeheader()
                writer.writerow(
                    {
                        "slot": "normal",
                        "source_kind": "crimson_normal",
                        "parameter_name": "_normalTexture",
                        "dds_path": "character/texture/blade_n.dds",
                        "suffix": "n",
                        "authority": "authoritative",
                    }
                )
            archive.write_text('{"normal_space": "green_up" if slot_key == "normal" else "auto"}', encoding="utf-8")
            helper.write_text('bool should_invert_green(){ return normal_space == "green_up"; } void invert_green_channel(){}', encoding="utf-8")
            d3d11.write_text('bool invert_normal_y = true; normal_y_policy.find("invert"); d3d11_normal_y_mode;', encoding="utf-8")

            report = build_normal_y_policy_report(
                audit_csv=audit,
                archive_source=archive,
                texture_helper_source=helper,
                d3d11_preview_source=d3d11,
            )

        self.assertEqual("inferred", report["status"])
        self.assertEqual("corpus_and_app_policy_inferred", report["authority"])
        self.assertEqual(1, report["audit"]["normal_rows"])
        self.assertEqual("green_up_asset_inverted_for_directx_preview", report["normal_y_mode"])

    def test_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out = root / "normal_y.json"
            archive = root / "archive.py"
            helper = root / "main.cpp"
            d3d11 = root / "d3d11.cpp"
            archive.write_text('{"normal_space": "green_up" if slot_key == "normal" else "auto"}', encoding="utf-8")
            helper.write_text('bool should_invert_green(){ return normal_space == "green_up"; } void invert_green_channel(){}', encoding="utf-8")
            d3d11.write_text('bool invert_normal_y = true; normal_y_policy.find("invert"); d3d11_normal_y_mode;', encoding="utf-8")

            self.assertEqual(
                0,
                main(
                    [
                        "--archive-source",
                        str(archive),
                        "--texture-helper-source",
                        str(helper),
                        "--d3d11-preview-source",
                        str(d3d11),
                        "--out-json",
                        str(out),
                    ]
                ),
            )
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual("inferred", payload["status"])


if __name__ == "__main__":
    unittest.main()
