from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile

from tools.correlate_renderdoc_dds_paths import (
    correlate_resources_to_dds,
    main,
    scan_dds_corpus,
    scan_resource_content_blobs,
)


def _fake_dds(width: int, height: int, *, mips: int = 1, fourcc: bytes = b"DXT1") -> bytes:
    data = bytearray(b"DDS " + bytes(124) + bytes(4096))
    struct.pack_into("<I", data, 4, 124)
    struct.pack_into("<I", data, 12, height)
    struct.pack_into("<I", data, 16, width)
    struct.pack_into("<I", data, 28, mips)
    struct.pack_into("<I", data, 76, 32)
    struct.pack_into("<I", data, 80, 0x4)
    data[84:88] = fourcc
    return bytes(data)


class RenderDocDdsCorrelationTests(unittest.TestCase):
    def test_correlates_unique_resource_by_format_dimensions_and_mips(self) -> None:
        report = {
            "captures": [
                {
                    "srv_slots": [
                        {
                            "resource": 42,
                            "format": "DXGI_FORMAT_BC5_UNORM",
                            "srgb_view": False,
                            "resource_desc": {"width": 1024, "height": 512, "mip_levels": 10},
                        }
                    ]
                }
            ]
        }
        dds_rows = [
            {
                "archive_path": "character/texture/blade_n.dds",
                "format": "BC5_UNORM",
                "family": "BC5",
                "width": 1024,
                "height": 512,
                "mip_count": 10,
                "role": "normal",
                "direct_upload_candidate": True,
            }
        ]

        correlated = correlate_resources_to_dds([report], dds_rows)

        self.assertEqual(1, correlated["matched_resource_count"])
        row = correlated["correlations"][0]
        self.assertEqual("capture_correlated_unique", row["authority"])
        self.assertEqual("high", row["confidence"])
        self.assertEqual("character/texture/blade_n.dds", row["correlated_dds_path"])

    def test_marks_dimension_only_match_ambiguous(self) -> None:
        report = {"srv_slots": [{"resource": 7, "format": "DXGI_FORMAT_R16G16_FLOAT", "resource_desc": {"width": 512, "height": 512}}]}
        dds_rows = [
            {"archive_path": "a.dds", "format": "BC1_UNORM", "family": "BC1", "width": 512, "height": 512, "mip_count": 10, "role": "base_or_layer"},
            {"archive_path": "b.dds", "format": "BC3_UNORM", "family": "BC3", "width": 512, "height": 512, "mip_count": 10, "role": "base_or_layer"},
        ]

        correlated = correlate_resources_to_dds([report], dds_rows)

        row = correlated["correlations"][0]
        self.assertEqual("dimension_only", row["match_kind"])
        self.assertEqual("ambiguous", row["confidence"])

    def test_cli_scans_dds_root_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "0000" / "character" / "texture" / "blade_n.dds"
            dds_path.parent.mkdir(parents=True)
            dds_path.write_bytes(_fake_dds(256, 256, mips=9, fourcc=b"BC5U"))
            capture = root / "capture.json"
            out_json = root / "correlation.json"
            out_csv = root / "correlation.csv"
            capture.write_text(
                json.dumps(
                    {
                        "srv_slots": [
                            {
                                "resource": 42,
                                "format": "DXGI_FORMAT_BC5_UNORM",
                                "resource_desc": {"width": 256, "height": 256, "mip_levels": 9},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                0,
                main(["--capture-report", str(capture), "--dds-root", str(root), "--out-json", str(out_json), "--out-csv", str(out_csv)]),
            )
            rows = scan_dds_corpus(root)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            csv_text = out_csv.read_text(encoding="utf-8")

        self.assertEqual("character/texture/blade_n.dds", rows[0]["archive_path"])
        self.assertEqual(1, payload["unique_high_confidence_count"])
        self.assertIn("correlated_dds_path", csv_text)

    def test_cli_marks_exact_blob_payload_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "0000" / "character" / "texture" / "blade_n.dds"
            dds_path.parent.mkdir(parents=True)
            dds_bytes = _fake_dds(128, 128, mips=1, fourcc=b"BC5U")
            dds_path.write_bytes(dds_bytes)
            capture = root / "capture.json"
            capture.write_text(
                json.dumps(
                    {
                        "srv_slots": [
                            {
                                "resource": 42,
                                "format": "DXGI_FORMAT_BC5_UNORM",
                                "resource_desc": {"width": 128, "height": 128, "mip_levels": 1},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            xml = root / "capture.xml"
            xml.write_text(
                """<capture><chunk name="Internal::Initial Contents" chunkIndex="9">
  <ResourceId name="id">42</ResourceId>
  <enum name="type" string="Resource">10</enum>
  <buffer name="ResourceContents" byteLength="4096">7</buffer>
</chunk></capture>""",
                encoding="utf-8",
            )
            zip_path = root / "capture.zip"
            with ZipFile(zip_path, "w") as archive:
                archive.writestr("000007", dds_bytes[128:])
            out_json = root / "correlation.json"

            self.assertEqual(
                0,
                main(
                    [
                        "--capture-report",
                        str(capture),
                        "--dds-root",
                        str(root),
                        "--capture-xml",
                        str(xml),
                        "--blob-zip",
                        str(zip_path),
                        "--out-json",
                        str(out_json),
                    ]
                ),
            )
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            blob_id = scan_resource_content_blobs(xml, {"42"})["42"]["blob_id"]

        row = payload["correlations"][0]
        self.assertEqual(1, payload["blob_hash_summary"]["exact_blob_match_count"])
        self.assertEqual("capture_blob_exact", row["authority"])
        self.assertEqual("character/texture/blade_n.dds", row["exact_blob_dds_path"])
        self.assertEqual("dds_payload_all", row["exact_blob_hash_kind"])
        self.assertEqual("7", blob_id)


if __name__ == "__main__":
    unittest.main()
