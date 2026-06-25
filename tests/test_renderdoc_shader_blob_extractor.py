from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from tools.extract_renderdoc_shader_blobs import (
    candidate_shader_refs,
    extract_shader_blobs,
    inspect_dxbc_container,
    main,
    parse_handle_creates_from_disassembly,
    parse_resource_bindings_from_disassembly,
    zip_entry_name,
)


def _fake_dxbc_with_dxil(payload: bytes = b"unit-dxil") -> bytes:
    part_offset = 36
    part = b"DXIL" + len(payload).to_bytes(4, "little") + payload
    size = part_offset + len(part)
    return (
        b"DXBC"
        + (b"\0" * 16)
        + (1).to_bytes(4, "little")
        + size.to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + part_offset.to_bytes(4, "little")
        + part
    )


class RenderDocShaderBlobExtractorTests(unittest.TestCase):
    def test_inspects_dxbc_dxil_part(self) -> None:
        inspection = inspect_dxbc_container(_fake_dxbc_with_dxil())

        self.assertEqual("DXBC", inspection["container_kind"])
        self.assertEqual("DXIL", inspection["shader_ir"])
        self.assertEqual("DXIL", inspection["parts"][0]["tag"])

    def test_collects_shader_refs_from_candidate(self) -> None:
        refs = candidate_shader_refs(
            {
                "pipeline_description": {
                    "shaders": {
                        "VS": {"blob_id": 7, "byte_length": 44},
                        "PS": {"blob_id": 8, "byte_length": 55},
                        "GS": {"blob_id": 9, "byte_length": 66},
                    }
                }
            },
            stages=("PS",),
        )

        self.assertEqual([{"stage": "PS", "blob_id": 8, "byte_length": 55}], refs)
        self.assertEqual("000008", zip_entry_name(8))

    def test_parses_dxc_resource_bindings(self) -> None:
        bindings = parse_resource_bindings_from_disassembly(
            "\n".join(
                [
                    "; Resource Bindings:",
                    ";",
                    "; Name                                 Type  Format         Dim      ID      HLSL Bind  Count",
                    "; ------------------------------ ---------- ------- ----------- ------- -------------- ------",
                    "; __x__SceneConstantBuffer           cbuffer      NA          NA     CB0   cb20,space35     1",
                    "; __x__g_samplerWrap                  sampler      NA          NA      S0     s8,space95     1",
                    "; __x__g_waterNormalTexture           texture     f32          2d      T4     t15,space36     1",
                    "; __x__g_bindlessTextures             texture     f32          2d      T5      t0,space7unbounded",
                    ";",
                    "target datalayout = \"dxil\"",
                ]
            )
        )

        self.assertEqual(4, len(bindings))
        self.assertEqual("texture", bindings[2]["type"])
        self.assertEqual(15, bindings[2]["register"])
        self.assertEqual(36, bindings[2]["space"])
        self.assertEqual("t15,space36", bindings[2]["hlsl_bind"])
        self.assertEqual("unbounded", bindings[3]["count"])
        self.assertEqual(7, bindings[3]["space"])

    def test_parses_create_handle_from_binding(self) -> None:
        creates = parse_handle_creates_from_disassembly(
            "  %205 = call %dx.types.Handle @dx.op.createHandleFromBinding(i32 217, "
            "%dx.types.ResBind { i32 0, i32 -1, i32 7, i8 0 }, i32 %204, i1 true)"
        )

        self.assertEqual(1, len(creates))
        self.assertEqual("srv", creates[0]["class"])
        self.assertEqual(7, creates[0]["space"])
        self.assertEqual("%204", creates[0]["index"])
        self.assertTrue(creates[0]["is_unbounded"])
        self.assertTrue(creates[0]["non_uniform"])

    def test_extracts_rank_shader_blobs_from_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "frame.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("000007", _fake_dxbc_with_dxil(b"vs"))
                zf.writestr("000008", _fake_dxbc_with_dxil(b"ps"))
            report = {
                "candidates": [
                    {
                        "rank": 1,
                        "chunk_index": 99,
                        "pipeline_description": {
                            "shaders": {
                                "VS": {"blob_id": 7, "byte_length": len(_fake_dxbc_with_dxil(b"vs"))},
                                "PS": {"blob_id": 8, "byte_length": len(_fake_dxbc_with_dxil(b"ps"))},
                            }
                        },
                    }
                ]
            }

            output = extract_shader_blobs(
                report,
                renderdoc_zip=archive,
                out_dir=root / "out",
                ranks=(1,),
            )

            self.assertEqual(2, output["blob_count"])
            self.assertEqual("DXIL", output["blobs"][0]["shader_ir"])
            self.assertTrue(Path(output["blobs"][0]["path"]).is_file())
            self.assertEqual("not_requested", output["disassembler"]["status"])

    def test_extracts_dxc_disassembly_bindings_when_requested(self) -> None:
        disassembly = "\n".join(
            [
                "; Resource Bindings:",
                "; Name Type Format Dim ID HLSL Bind Count",
                "; __x__SceneConstantBuffer cbuffer NA NA CB0 cb2,space1 1",
                "; __x__BaseTexture texture f32 2d T0 t4,space3 1",
                "target datalayout = \"dxil\"",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "frame.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("000008", _fake_dxbc_with_dxil(b"ps"))
            report = {
                "candidates": [
                    {
                        "rank": 1,
                        "chunk_index": 99,
                        "pipeline_description": {"shaders": {"PS": {"blob_id": 8, "byte_length": len(_fake_dxbc_with_dxil(b"ps"))}}},
                    }
                ]
            }

            with mock.patch(
                "tools.extract_renderdoc_shader_blobs.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=disassembly, stderr=""),
            ):
                output = extract_shader_blobs(report, renderdoc_zip=archive, out_dir=root / "out", ranks=(1,), dxc=Path("dxc.exe"))

        blob = output["blobs"][0]
        self.assertEqual("used", output["disassembler"]["status"])
        self.assertEqual("ok", blob["disassembly_status"])
        self.assertTrue(blob["disassembly_path"].endswith(".asm"))
        self.assertEqual("t4,space3", blob["resource_bindings"][1]["hlsl_bind"])

    def test_records_missing_zip_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "frame.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("000007", _fake_dxbc_with_dxil())

            output = extract_shader_blobs(
                {
                    "candidates": [
                        {
                            "rank": 1,
                            "chunk_index": 10,
                            "pipeline_description": {"shaders": {"PS": {"blob_id": 8, "byte_length": 1}}},
                        }
                    ]
                },
                renderdoc_zip=archive,
                out_dir=root / "out",
                ranks=(1,),
            )

        self.assertEqual(0, output["blob_count"])
        self.assertEqual(1, output["missing_count"])
        self.assertEqual("000008", output["missing"][0]["entry"])

    def test_cli_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "candidates.json"
            archive = root / "frame.zip"
            out_json = root / "manifest.json"
            source.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "rank": 1,
                                "chunk_index": 22,
                                "pipeline_description": {"shaders": {"PS": {"blob_id": 8, "byte_length": 0}}},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("000008", _fake_dxbc_with_dxil())

            self.assertEqual(
                0,
                main(
                    [
                        "--draw-candidates-json",
                        str(source),
                        "--renderdoc-zip",
                        str(archive),
                        "--out-dir",
                        str(root / "out"),
                        "--out-json",
                        str(out_json),
                        "--rank",
                        "1",
                    ]
                ),
            )
            payload = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(1, payload["blob_count"])


if __name__ == "__main__":
    unittest.main()
