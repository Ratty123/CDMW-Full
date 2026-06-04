from __future__ import annotations

import json
from pathlib import Path
import tempfile
import textwrap
import unittest

from tools.locate_renderdoc_dispatch_truth_candidates import locate_dispatch_truth_candidates, main


class RenderDocDispatchTruthCandidateTests(unittest.TestCase):
    def test_locates_compute_dispatch_with_cs_bytecode(self) -> None:
        xml = Path(tempfile.mkdtemp()) / "capture.xml"
        xml.write_text(
            textwrap.dedent(
                """\
                <root>
                  <chunk chunkIndex="1" name="ID3D12Device::CreateRootSignature">
                    <ResourceId name="pRootSignature">33</ResourceId>
                    <buffer name="pBlobWithRootSignature" byteLength="64">77</buffer>
                    <uint name="blobLengthInBytes">64</uint>
                  </chunk>
                  <chunk chunkIndex="2" name="ID3D12Device::CreateComputePipeline">
                    <struct name="pDesc">
                      <ResourceId name="pRootSignature">33</ResourceId>
                      <struct name="CS">
                        <buffer name="pShaderBytecode" byteLength="128">88</buffer>
                        <uint name="BytecodeLength">128</uint>
                      </struct>
                      <enum name="Flags" string="D3D12_PIPELINE_STATE_FLAG_NONE">0</enum>
                    </struct>
                    <ResourceId name="pPipelineState">22</ResourceId>
                    <ResourceId name="InlineShaderID">99</ResourceId>
                  </chunk>
                  <chunk chunkIndex="3" name="ID3D12GraphicsCommandList::SetPipelineState">
                    <ResourceId name="pCommandList">10</ResourceId>
                    <ResourceId name="pPipelineState">22</ResourceId>
                  </chunk>
                  <chunk chunkIndex="4" name="ID3D12GraphicsCommandList::SetComputeRootSignature">
                    <ResourceId name="pCommandList">10</ResourceId>
                    <ResourceId name="pRootSignature">33</ResourceId>
                  </chunk>
                  <chunk chunkIndex="5" name="ID3D12GraphicsCommandList::Dispatch">
                    <ResourceId name="pCommandList">10</ResourceId>
                    <uint name="ThreadGroupCountX">8</uint>
                    <uint name="ThreadGroupCountY">4</uint>
                    <uint name="ThreadGroupCountZ">2</uint>
                  </chunk>
                </root>
                """
            ),
            encoding="utf-8",
        )

        report = locate_dispatch_truth_candidates(xml)

        self.assertEqual(1, report["candidate_count"])
        candidate = report["candidates"][0]
        self.assertEqual(64, candidate["dispatch_groups"]["total"])
        self.assertEqual(22, candidate["state"]["pipeline_state"])
        self.assertEqual(33, candidate["state"]["compute_root_signature"])
        self.assertEqual(88, candidate["pipeline_description"]["shaders"]["CS"]["blob_id"])
        self.assertEqual(128, candidate["pipeline_description"]["shaders"]["CS"]["byte_length"])

    def test_cli_writes_dispatch_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xml = root / "capture.xml"
            out_json = root / "dispatch.json"
            xml.write_text(
                """<root>
                <chunk chunkIndex="1" name="ID3D12GraphicsCommandList::Dispatch">
                  <ResourceId name="pCommandList">10</ResourceId>
                  <uint name="ThreadGroupCountX">1</uint>
                  <uint name="ThreadGroupCountY">1</uint>
                  <uint name="ThreadGroupCountZ">1</uint>
                </chunk>
                </root>""",
                encoding="utf-8",
            )

            self.assertEqual(0, main(["--xml", str(xml), "--out-json", str(out_json)]))
            payload = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(1, payload["candidate_count"])


if __name__ == "__main__":
    unittest.main()
