from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.locate_renderdoc_draw_truth_candidates import locate_draw_truth_candidates, main


class RenderDocDrawTruthCandidateTests(unittest.TestCase):
    def test_locates_draw_with_pso_root_table_and_resolved_srv(self) -> None:
        xml = """<?xml version="1.0"?>
<capture>
  <chunk chunkIndex="1" name="ID3D12Device10::Device_CreatePlacedResource2" threadID="1">
    <struct name="pDesc">
      <enum name="Dimension" string="D3D12_RESOURCE_DIMENSION_TEXTURE2D">3</enum>
      <uint name="Width">1024</uint><uint name="Height">512</uint>
      <uint name="DepthOrArraySize">1</uint><uint name="MipLevels">8</uint>
      <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
      <enum name="Layout" string="D3D12_TEXTURE_LAYOUT_UNKNOWN">0</enum>
      <enum name="Flags" string="D3D12_RESOURCE_FLAG_NONE">0</enum>
    </struct>
    <ResourceId name="pResource">42</ResourceId>
  </chunk>
  <chunk chunkIndex="2" name="ID3D12Device::CreateShaderResourceView" threadID="1">
    <struct name="desc">
      <ResourceId name="Resource">42</ResourceId>
      <struct name="Descriptor">
        <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
        <enum name="ViewDimension" string="D3D12_SRV_DIMENSION_TEXTURE2D">4</enum>
        <enum name="Shader4ComponentMapping" string="RGBA">5768</enum>
      </struct>
    </struct>
    <struct name="dst"><ResourceId name="heap">7</ResourceId><uint name="index">5</uint></struct>
  </chunk>
  <chunk chunkIndex="3" name="ID3D12Device::CopyDescriptorsSimple" threadID="1">
    <array name="DescriptorCopies">
      <struct>
        <struct name="dst"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
        <struct name="src"><ResourceId name="heap">7</ResourceId><uint name="index">5</uint></struct>
      </struct>
    </array>
  </chunk>
  <chunk chunkIndex="4" name="ID3D12Device::CreateRootSignature" threadID="1">
    <buffer name="pBlobWithRootSignature" byteLength="64">77</buffer>
    <uint name="blobLengthInBytes">64</uint>
    <ResourceId name="pRootSignature">33</ResourceId>
  </chunk>
  <chunk chunkIndex="5" name="ID3D12Device2::CreatePipelineState" threadID="1">
    <struct name="pDesc">
      <ResourceId name="pRootSignature">33</ResourceId>
      <struct name="VS"><buffer name="pShaderBytecode" byteLength="128">88</buffer><uint name="BytecodeLength">128</uint></struct>
      <struct name="PS"><buffer name="pShaderBytecode" byteLength="256">89</buffer><uint name="BytecodeLength">256</uint></struct>
      <struct name="BlendState">
        <int name="AlphaToCoverageEnable">0</int><int name="IndependentBlendEnable">0</int>
        <array name="RenderTarget"><struct><bool name="BlendEnable">false</bool><enum name="SrcBlend" string="D3D12_BLEND_ONE">2</enum><enum name="DestBlend" string="D3D12_BLEND_ZERO">1</enum><enum name="RenderTargetWriteMask" string="D3D12_COLOR_WRITE_ENABLE_ALL">15</enum></struct></array>
      </struct>
      <struct name="RasterizerState"><enum name="CullMode" string="D3D12_CULL_MODE_BACK">3</enum><int name="DepthClipEnable">1</int></struct>
      <struct name="DepthStencilState"><int name="DepthEnable">1</int><enum name="DepthFunc" string="D3D12_COMPARISON_FUNC_LESS_EQUAL">4</enum></struct>
      <enum name="PrimitiveTopologyType" string="D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE">3</enum>
      <uint name="NumRenderTargets">1</uint>
      <array name="RTVFormats"><enum string="DXGI_FORMAT_R16G16B16A16_FLOAT">10</enum></array>
      <enum name="DSVFormat" string="DXGI_FORMAT_D32_FLOAT">40</enum>
    </struct>
    <ResourceId name="pPipelineState">22</ResourceId>
    <array name="InlineShaderIDs"><ResourceId>91</ResourceId><ResourceId>0</ResourceId><ResourceId>0</ResourceId><ResourceId>0</ResourceId><ResourceId>92</ResourceId></array>
  </chunk>
  <chunk chunkIndex="6" name="ID3D12GraphicsCommandList::SetPipelineState" threadID="1">
    <ResourceId name="pCommandList">11</ResourceId>
    <ResourceId name="pPipelineState">22</ResourceId>
  </chunk>
  <chunk chunkIndex="7" name="ID3D12GraphicsCommandList::SetGraphicsRootSignature" threadID="1">
    <ResourceId name="pCommandList">11</ResourceId>
    <ResourceId name="pRootSignature">33</ResourceId>
  </chunk>
  <chunk chunkIndex="8" name="ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable" threadID="1">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">4</uint>
    <struct name="BaseDescriptor"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
  </chunk>
  <chunk chunkIndex="9" name="ID3D12GraphicsCommandList::SetGraphicsRootConstantBufferView" threadID="1">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">1</uint>
    <struct name="BufferLocation"><ResourceId name="Buffer">55</ResourceId><uint name="Offset">256</uint></struct>
  </chunk>
  <chunk chunkIndex="10" name="ID3D12GraphicsCommandList::DrawIndexedInstanced" threadID="1">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="IndexCountPerInstance">123</uint><uint name="InstanceCount">1</uint>
    <uint name="StartIndexLocation">0</uint><int name="BaseVertexLocation">0</int>
  </chunk>
</capture>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.xml"
            path.write_text(xml, encoding="utf-8")

            report = locate_draw_truth_candidates(path, descriptor_window=1)

        self.assertEqual(1, report["draw_indexed_count"])
        candidate = report["candidates"][0]
        self.assertEqual(22, candidate["state"]["pipeline_state"])
        self.assertEqual(33, candidate["state"]["graphics_root_signature"])
        descriptor = candidate["state"]["root_descriptor_tables"]["4"]["descriptors"][0]
        self.assertEqual("SRV", descriptor["type"])
        self.assertEqual("DXGI_FORMAT_BC7_UNORM_SRGB", descriptor["resource_desc"]["format"])
        self.assertEqual(256, candidate["pipeline_description"]["shaders"]["PS"]["byte_length"])
        self.assertEqual(55, candidate["state"]["root_cbvs"]["1"]["resource"])
        self.assertEqual(256, candidate["state"]["root_cbvs"]["1"]["offset"])
        self.assertEqual("D3D12_CULL_MODE_BACK", candidate["pipeline_description"]["raster_state"]["cull_mode"])
        self.assertEqual("DXGI_FORMAT_R16G16B16A16_FLOAT", candidate["pipeline_description"]["rtv_formats"][0])
        self.assertEqual(64, candidate["root_signature_description"]["blob_length"])

    def test_resolves_srv_from_initial_descriptor_dump(self) -> None:
        xml = """<capture>
  <chunk chunkIndex="1" name="ID3D12Device10::Device_CreatePlacedResource2">
    <struct name="pDesc">
      <enum name="Dimension" string="D3D12_RESOURCE_DIMENSION_TEXTURE2D">3</enum>
      <uint name="Width">2048</uint><uint name="Height">1024</uint>
      <uint name="DepthOrArraySize">1</uint><uint name="MipLevels">10</uint>
      <enum name="Format" string="DXGI_FORMAT_BC1_UNORM_SRGB">72</enum>
    </struct>
    <ResourceId name="pResource">42</ResourceId>
  </chunk>
  <chunk chunkIndex="2" name="Internal::Initial Contents">
    <array>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="SRV">4097</enum>
        <ResourceId name="heap">9</ResourceId>
        <uint name="index">100</uint>
        <ResourceId name="Resource">42</ResourceId>
        <struct name="Descriptor">
          <enum name="Format" string="DXGI_FORMAT_BC1_UNORM_SRGB">72</enum>
          <enum name="ViewDimension" string="D3D12_SRV_DIMENSION_TEXTURE2D">4</enum>
          <enum name="Shader4ComponentMapping" string="RGBA">5768</enum>
        </struct>
      </struct>
    </array>
  </chunk>
  <chunk chunkIndex="3" name="ID3D12Resource::SetName">
    <ResourceId name="pResource">42</ResourceId>
    <string name="Name">WeaponAlbedo</string>
  </chunk>
  <chunk chunkIndex="4" name="Internal::Initial Contents">
    <array>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="SRV">4097</enum>
        <ResourceId name="heap">9</ResourceId>
        <uint name="index">100</uint>
        <ResourceId name="Resource">42</ResourceId>
        <struct name="Descriptor">
          <enum name="Format" string="DXGI_FORMAT_BC1_UNORM_SRGB">72</enum>
          <enum name="ViewDimension" string="D3D12_SRV_DIMENSION_TEXTURE2D">4</enum>
          <enum name="Shader4ComponentMapping" string="RGBA">5768</enum>
        </struct>
      </struct>
    </array>
  </chunk>
  <chunk chunkIndex="5" name="ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">4</uint>
    <struct name="BaseDescriptor"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
  </chunk>
  <chunk chunkIndex="6" name="ID3D12GraphicsCommandList::DrawIndexedInstanced">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="IndexCountPerInstance">3</uint><uint name="InstanceCount">1</uint>
  </chunk>
</capture>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.xml"
            path.write_text(xml, encoding="utf-8")

            report = locate_draw_truth_candidates(path, descriptor_window=1)

        descriptor = report["candidates"][0]["state"]["root_descriptor_tables"]["4"]["descriptors"][0]
        self.assertEqual("initial_contents_descriptor", descriptor["source"])
        self.assertEqual("DXGI_FORMAT_BC1_UNORM_SRGB", descriptor["format"])
        self.assertEqual(2048, descriptor["resource_desc"]["width"])
        self.assertEqual("WeaponAlbedo", descriptor["resource_desc"]["name"])
        self.assertEqual(1, report["resource_name_count"])

    def test_preserves_initial_descriptor_cbv_and_sampler_types(self) -> None:
        xml = """<capture>
  <chunk chunkIndex="1" name="Internal::Initial Contents">
    <array>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="CBV">4096</enum>
        <ResourceId name="heap">9</ResourceId><uint name="index">100</uint>
        <struct name="Descriptor">
          <struct name="BufferLocation"><ResourceId name="Buffer">42</ResourceId><uint name="Offset">64</uint></struct>
          <uint name="SizeInBytes">256</uint>
        </struct>
      </struct>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="Sampler">0</enum>
        <ResourceId name="heap">9</ResourceId><uint name="index">101</uint>
        <struct name="Descriptor">
          <enum name="Filter" string="D3D12_FILTER_ANISOTROPIC">85</enum>
          <enum name="AddressU" string="D3D12_TEXTURE_ADDRESS_MODE_WRAP">1</enum>
          <enum name="AddressV" string="D3D12_TEXTURE_ADDRESS_MODE_CLAMP">3</enum>
          <uint name="MaxAnisotropy">16</uint>
        </struct>
      </struct>
    </array>
  </chunk>
  <chunk chunkIndex="2" name="ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">4</uint>
    <struct name="BaseDescriptor"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
  </chunk>
  <chunk chunkIndex="3" name="ID3D12GraphicsCommandList::DrawIndexedInstanced">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="IndexCountPerInstance">3</uint><uint name="InstanceCount">1</uint>
  </chunk>
</capture>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.xml"
            path.write_text(xml, encoding="utf-8")

            report = locate_draw_truth_candidates(path, descriptor_window=2)

        descriptors = report["candidates"][0]["state"]["root_descriptor_tables"]["4"]["descriptors"]
        self.assertEqual("CBV", descriptors[0]["type"])
        self.assertEqual(42, descriptors[0]["buffer_resource"])
        self.assertEqual(256, descriptors[0]["size_in_bytes"])
        self.assertEqual("Sampler", descriptors[1]["type"])
        self.assertEqual("D3D12_FILTER_ANISOTROPIC", descriptors[1]["filter"])

    def test_ranks_material_draw_before_earlier_screen_triangle(self) -> None:
        xml = """<capture>
  <chunk chunkIndex="1" name="ID3D12Device10::Device_CreatePlacedResource2">
    <struct name="pDesc">
      <enum name="Dimension" string="D3D12_RESOURCE_DIMENSION_TEXTURE2D">3</enum>
      <uint name="Width">2048</uint><uint name="Height">1024</uint>
      <uint name="DepthOrArraySize">1</uint><uint name="MipLevels">10</uint>
      <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
    </struct>
    <ResourceId name="pResource">42</ResourceId>
  </chunk>
  <chunk chunkIndex="2" name="Internal::Initial Contents">
    <array>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="SRV">4097</enum>
        <ResourceId name="heap">9</ResourceId><uint name="index">100</uint>
        <ResourceId name="Resource">42</ResourceId>
        <struct name="Descriptor">
          <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
          <enum name="ViewDimension" string="D3D12_SRV_DIMENSION_TEXTURE2D">4</enum>
        </struct>
      </struct>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="Sampler">0</enum>
        <ResourceId name="heap">9</ResourceId><uint name="index">101</uint>
        <struct name="Descriptor"><enum name="Filter" string="D3D12_FILTER_ANISOTROPIC">85</enum></struct>
      </struct>
      <struct typename="D3D12Descriptor">
        <enum name="type" string="CBV">4096</enum>
        <ResourceId name="heap">9</ResourceId><uint name="index">102</uint>
        <struct name="Descriptor">
          <struct name="BufferLocation"><ResourceId name="Buffer">55</ResourceId><uint name="Offset">0</uint></struct>
          <uint name="SizeInBytes">256</uint>
        </struct>
      </struct>
    </array>
  </chunk>
  <chunk chunkIndex="3" name="ID3D12Device2::CreatePipelineState">
    <struct name="pDesc">
      <ResourceId name="pRootSignature">33</ResourceId>
      <struct name="VS"><buffer name="pShaderBytecode" byteLength="128">88</buffer></struct>
      <struct name="PS"><buffer name="pShaderBytecode" byteLength="128">89</buffer></struct>
    </struct>
    <ResourceId name="pPipelineState">22</ResourceId>
  </chunk>
  <chunk chunkIndex="4" name="ID3D12Device2::CreatePipelineState">
    <struct name="pDesc">
      <ResourceId name="pRootSignature">33</ResourceId>
      <struct name="VS"><buffer name="pShaderBytecode" byteLength="128">188</buffer></struct>
      <struct name="PS"><buffer name="pShaderBytecode" byteLength="256">189</buffer></struct>
    </struct>
    <ResourceId name="pPipelineState">44</ResourceId>
  </chunk>
  <chunk chunkIndex="5" name="ID3D12GraphicsCommandList::SetPipelineState">
    <ResourceId name="pCommandList">11</ResourceId><ResourceId name="pPipelineState">22</ResourceId>
  </chunk>
  <chunk chunkIndex="6" name="ID3D12GraphicsCommandList::DrawIndexedInstanced">
    <ResourceId name="pCommandList">11</ResourceId><uint name="IndexCountPerInstance">3</uint><uint name="InstanceCount">1</uint>
  </chunk>
  <chunk chunkIndex="7" name="ID3D12GraphicsCommandList::SetPipelineState">
    <ResourceId name="pCommandList">11</ResourceId><ResourceId name="pPipelineState">44</ResourceId>
  </chunk>
  <chunk chunkIndex="8" name="ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">4</uint>
    <struct name="BaseDescriptor"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
  </chunk>
  <chunk chunkIndex="9" name="ID3D12GraphicsCommandList::DrawIndexedInstanced">
    <ResourceId name="pCommandList">11</ResourceId><uint name="IndexCountPerInstance">1200</uint><uint name="InstanceCount">1</uint>
  </chunk>
</capture>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.xml"
            path.write_text(xml, encoding="utf-8")

            report = locate_draw_truth_candidates(path, descriptor_window=3)

        top = report["candidates"][0]
        self.assertEqual(9, top["chunk_index"])
        self.assertEqual(1, top["rank"])
        self.assertEqual(2, top["action_rank"])
        self.assertEqual(1, top["selection_evidence"]["bc_srv_count"])
        self.assertEqual(1, top["selection_evidence"]["sampler_count"])
        self.assertEqual(1, top["selection_evidence"]["constant_buffer_count"])

    def test_cli_writes_json_and_csv(self) -> None:
        xml = """<capture>
  <chunk chunkIndex="1" name="ID3D12GraphicsCommandList::SetPipelineState"><ResourceId name="pCommandList">1</ResourceId><ResourceId name="pPipelineState">2</ResourceId></chunk>
  <chunk chunkIndex="2" name="ID3D12GraphicsCommandList::DrawIndexedInstanced"><ResourceId name="pCommandList">1</ResourceId><uint name="IndexCountPerInstance">6</uint><uint name="InstanceCount">1</uint></chunk>
</capture>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "capture.xml"
            out_json = root / "candidates.json"
            out_csv = root / "candidates.csv"
            source.write_text(xml, encoding="utf-8")

            self.assertEqual(
                0,
                main(["--xml", str(source), "--out-json", str(out_json), "--out-csv", str(out_csv)]),
            )
            report = json.loads(out_json.read_text(encoding="utf-8"))
            csv_text = out_csv.read_text(encoding="utf-8")

        self.assertEqual(1, report["candidate_count"])
        self.assertIn("pipeline_state", csv_text)


if __name__ == "__main__":
    unittest.main()
