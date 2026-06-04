from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.summarize_renderdoc_shader_bindings import main, summarize_shader_bindings


class RenderDocShaderBindingSummaryTests(unittest.TestCase):
    def test_summarizes_bindless_spaces_and_keyword_hits(self) -> None:
        report = summarize_shader_bindings(
            [
                {
                    "renderdoc_zip": "frame.zip",
                    "blobs": [
                        {
                            "rank": 1,
                            "chunk_index": 20,
                            "stage": "PS",
                            "blob_id": 8,
                            "sha256": "hash",
                            "resource_bindings": [
                                {
                                    "name": "__0__7__0__0__g_bindlessTextures",
                                    "type": "texture",
                                    "hlsl_bind": "t0,space7",
                                    "space": 7,
                                    "count": "unbounded",
                                },
                                {
                                    "name": "__3__35__0__0__MaterialConstantBuffer",
                                    "type": "cbuffer",
                                    "hlsl_bind": "cb50,space35",
                                    "space": 35,
                                    "count": 1,
                                },
                            ],
                            "handle_creates": [
                                {"class": "srv", "space": 7, "is_unbounded": True},
                            ],
                        }
                    ],
                }
            ]
        )

        self.assertEqual(1, report["blob_count"])
        self.assertEqual(7, report["bindless_spaces"][0]["space"])
        self.assertEqual("srv", report["dynamic_handle_spaces"][0]["class"])
        self.assertIn("__3__35__0__0__MaterialConstantBuffer", {item["name"] for item in report["keyword_hits"]})

    def test_cli_writes_summary_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "manifest.json"
            out_json = root / "summary.json"
            out_csv = root / "summary.csv"
            manifest.write_text(
                json.dumps(
                    {
                        "blobs": [
                            {
                                "rank": 2,
                                "stage": "CS",
                                "resource_bindings": [],
                                "handle_creates": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                0,
                main(
                    [
                        "--shader-blob-manifest",
                        str(manifest),
                        "--out-json",
                        str(out_json),
                        "--out-csv",
                        str(out_csv),
                    ]
                ),
            )
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertTrue(out_csv.is_file())

        self.assertEqual(1, payload["blob_count"])


if __name__ == "__main__":
    unittest.main()
