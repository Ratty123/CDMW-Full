from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.analyze_renderdoc_capture_xml import main, summarize_renderdoc_capture_xml


FIXTURE_XML = """<?xml version="1.0"?>
<rdc>
  <header>
    <driver id="4">D3D12</driver>
    <thumbnail width="1280" height="720">thumb.jpg</thumbnail>
  </header>
  <chunks version="32">
    <chunk name="Internal::Driver Initialisation Parameters" chunkIndex="0">
      <struct name="AdapterDesc">
        <string name="Description">GPU Name</string>
        <uint name="VendorId">4098</uint>
        <uint name="DeviceId">123</uint>
        <uint name="DedicatedVideoMemory">4096</uint>
      </struct>
      <bool name="usedDXIL">true</bool>
      <enum name="VendorExtensions" string="AMD">2</enum>
      <uint name="SDKVersion">618</uint>
    </chunk>
    <chunk name="ID3D12Device::CreateCommittedResource" chunkIndex="1">
      <struct name="pDesc">
        <enum name="Dimension" string="D3D12_RESOURCE_DIMENSION_TEXTURE2D">3</enum>
        <uint name="Width">1024</uint>
        <uint name="Height">512</uint>
        <uint name="MipLevels">8</uint>
        <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
        <enum name="Flags" string="D3D12_RESOURCE_FLAG_NONE">0</enum>
      </struct>
      <ResourceId name="pResource">77</ResourceId>
    </chunk>
    <chunk name="ID3D12Device::CreateShaderResourceView" chunkIndex="2">
      <struct name="Descriptor">
        <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
        <enum name="ViewDimension" string="D3D12_SRV_DIMENSION_TEXTURE2D">4</enum>
        <enum name="Shader4ComponentMapping" string="RGBA">5768</enum>
        <uint name="MostDetailedMip">0</uint>
        <uint name="MipLevels">8</uint>
      </struct>
      <ResourceId name="Resource">77</ResourceId>
      <struct name="dst">
        <ResourceId name="heap">88</ResourceId>
        <uint name="index">9</uint>
      </struct>
    </chunk>
    <chunk name="ID3D12GraphicsCommandList::SetPipelineState" chunkIndex="3">
      <ResourceId name="pCommandList">1</ResourceId>
      <ResourceId name="pPipelineState">2</ResourceId>
    </chunk>
    <chunk name="ID3D12GraphicsCommandList::DrawIndexedInstanced" chunkIndex="4">
      <ResourceId name="pCommandList">1</ResourceId>
      <uint name="IndexCountPerInstance">36</uint>
      <uint name="InstanceCount">2</uint>
    </chunk>
  </chunks>
</rdc>
"""


class RenderDocCaptureXmlAnalyzerTests(unittest.TestCase):
    def test_summarizes_driver_resources_srvs_and_draws(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml = Path(temp_dir) / "capture.xml"
            xml.write_text(FIXTURE_XML, encoding="utf-8")

            summary = summarize_renderdoc_capture_xml(xml, scene_note="unit")

        self.assertEqual("D3D12", summary["header"]["driver"])
        self.assertEqual("GPU Name", summary["adapter"]["description"])
        self.assertEqual("DXGI_FORMAT_BC7_UNORM_SRGB", summary["resource_format_counts"][0]["value"])
        self.assertEqual("DXGI_FORMAT_BC7_UNORM_SRGB", summary["srv_format_counts"][0]["value"])
        self.assertEqual("ID3D12GraphicsCommandList::DrawIndexedInstanced", summary["draw_counts"][0]["value"])
        self.assertEqual(36, summary["samples"]["draws"][0]["IndexCountPerInstance"])
        self.assertEqual("unit", summary["scene_note"])

    def test_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xml = root / "capture.xml"
            out = root / "summary.json"
            xml.write_text(FIXTURE_XML, encoding="utf-8")

            self.assertEqual(0, main(["--xml", str(xml), "--out-json", str(out), "--scene-note", "cli"]))
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual("xml_summarized", payload["status"])
        self.assertEqual("cli", payload["scene_note"])


if __name__ == "__main__":
    unittest.main()
