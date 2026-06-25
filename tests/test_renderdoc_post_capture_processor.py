from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from zipfile import ZipFile

from tools.process_renderdoc_capture_reports import convert_capture_artifacts, main, process_capture_reports


def _write_dds(path: Path, *, width: int, height: int, mips: int, fourcc: bytes = b"BC7U") -> None:
    data = bytearray(160)
    data[:4] = b"DDS "
    struct.pack_into("<I", data, 12, height)
    struct.pack_into("<I", data, 16, width)
    struct.pack_into("<I", data, 28, mips)
    data[84:88] = fourcc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class RenderDocPostCaptureProcessorTests(unittest.TestCase):
    def test_processes_xml_and_blob_zip_into_target_status_reports(self) -> None:
        xml = _target_capture_xml()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture_xml = root / "capture.xml"
            capture_xml.write_text(xml, encoding="utf-8")
            blob_zip = root / "capture_blobs.zip"
            with ZipFile(blob_zip, "w") as archive:
                archive.writestr("000088", b"vs")
                archive.writestr("000089", b"ps")
            dds_root = root / "dds"
            _write_dds(dds_root / "character" / "texture" / "weapon_blade.dds", width=1024, height=512, mips=8)

            summary = process_capture_reports(
                root / "run",
                capture_xml=capture_xml,
                blob_zip=blob_zip,
                capture_path=root / "frame.rdc",
                dds_root=dds_root,
                rank=1,
            )

            status = json.loads((root / "run" / "reports" / "status.json").read_text(encoding="utf-8"))
            truth = json.loads((root / "run" / "reports" / "truth_report_rank1.json").read_text(encoding="utf-8"))
            dds = json.loads((root / "run" / "reports" / "dds_correlation.json").read_text(encoding="utf-8"))
            shader_blobs = json.loads((root / "run" / "reports" / "shader_blobs.json").read_text(encoding="utf-8"))

        self.assertEqual("capture_reports_processed", summary["status"])
        self.assertEqual("WeaponBladeAlbedo", truth["captures"][0]["srv_slots"][0]["resource_name"])
        self.assertEqual(2, shader_blobs["blob_count"])
        target = next(item for item in status["plan_items"] if item["name"] == "renderdoc_target_material_selection")
        self.assertEqual("complete", target["status"])
        self.assertGreaterEqual(dds["unique_high_confidence_count"], 1)

    def test_process_records_missing_dds_root_as_explicit_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture_xml = root / "capture.xml"
            capture_xml.write_text(_target_capture_xml(), encoding="utf-8")
            blob_zip = root / "capture_blobs.zip"
            with ZipFile(blob_zip, "w") as archive:
                archive.writestr("000088", b"vs")
                archive.writestr("000089", b"ps")

            process_capture_reports(
                root / "run",
                capture_xml=capture_xml,
                blob_zip=blob_zip,
                capture_path=root / "frame.rdc",
                dds_root=root / "missing-dds",
                rank=1,
            )

            reports = root / "run" / "reports"
            dds = json.loads((reports / "dds_correlation.json").read_text(encoding="utf-8"))
            status = json.loads((reports / "status.json").read_text(encoding="utf-8"))

        self.assertEqual("dds_root_not_found", dds["blocker"])
        correlation = next(item for item in status["plan_items"] if item["name"] == "renderdoc_dds_path_correlation")
        self.assertEqual("blocked_external", correlation["status"])

    def test_convert_capture_artifacts_runs_thumb_and_convert_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rdc = root / "frame.rdc"
            rdc.write_bytes(b"rdc")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            commands: list[list[str]] = []

            def runner(command: list[str], **_: object) -> SimpleNamespace:
                commands.append(command)
                if command[1] == "convert":
                    Path(command[5]).write_text("<capture />", encoding="utf-8")
                    Path(command[5]).with_suffix("").write_bytes(b"PK\x05\x06" + b"\0" * 18)
                elif command[1] == "thumb":
                    Path(command[3]).write_bytes(b"jpg")
                return SimpleNamespace(returncode=0)

            report = convert_capture_artifacts(rdc, renderdoccmd=renderdoccmd, runner=runner)

        self.assertEqual("converted", report["status"])
        self.assertEqual("thumb", commands[0][1])
        self.assertEqual("convert", commands[1][1])
        self.assertEqual(str(rdc), report["capture_path"])

    def test_cli_blocks_when_raw_rdc_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out = main(["--run-dir", str(root / "run"), "--rdc", str(root / "missing.rdc"), "--renderdoccmd", str(root / "missing-renderdoccmd.exe")])

        self.assertEqual(2, out)


def _target_capture_xml() -> str:
    return """<capture>
  <chunk chunkIndex="1" name="ID3D12Device10::Device_CreatePlacedResource2">
    <struct name="pDesc">
      <enum name="Dimension" string="D3D12_RESOURCE_DIMENSION_TEXTURE2D">3</enum>
      <uint name="Width">1024</uint><uint name="Height">512</uint>
      <uint name="DepthOrArraySize">1</uint><uint name="MipLevels">8</uint>
      <enum name="Format" string="DXGI_FORMAT_BC7_UNORM_SRGB">99</enum>
    </struct>
    <ResourceId name="pResource">42</ResourceId>
  </chunk>
  <chunk chunkIndex="2" name="ID3D12Resource::SetName">
    <ResourceId name="pResource">42</ResourceId>
    <string name="Name">WeaponBladeAlbedo</string>
  </chunk>
  <chunk chunkIndex="3" name="Internal::Initial Contents">
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
  <chunk chunkIndex="4" name="ID3D12Device::CreateRootSignature">
    <buffer name="pBlobWithRootSignature" byteLength="64">77</buffer>
    <ResourceId name="pRootSignature">33</ResourceId>
  </chunk>
  <chunk chunkIndex="5" name="ID3D12Device2::CreatePipelineState">
    <struct name="pDesc">
      <ResourceId name="pRootSignature">33</ResourceId>
      <struct name="VS"><buffer name="pShaderBytecode" byteLength="128">88</buffer></struct>
      <struct name="PS"><buffer name="pShaderBytecode" byteLength="256">89</buffer></struct>
      <struct name="BlendState"><int name="AlphaToCoverageEnable">0</int><array name="RenderTarget"><struct><bool name="BlendEnable">false</bool></struct></array></struct>
      <struct name="RasterizerState"><enum name="CullMode" string="D3D12_CULL_MODE_BACK">3</enum></struct>
    </struct>
    <ResourceId name="pPipelineState">22</ResourceId>
  </chunk>
  <chunk chunkIndex="6" name="ID3D12GraphicsCommandList::SetPipelineState">
    <ResourceId name="pCommandList">11</ResourceId><ResourceId name="pPipelineState">22</ResourceId>
  </chunk>
  <chunk chunkIndex="7" name="ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable">
    <ResourceId name="pCommandList">11</ResourceId>
    <uint name="RootParameterIndex">4</uint>
    <struct name="BaseDescriptor"><ResourceId name="heap">9</ResourceId><uint name="index">100</uint></struct>
  </chunk>
  <chunk chunkIndex="8" name="ID3D12GraphicsCommandList::DrawIndexedInstanced">
    <ResourceId name="pCommandList">11</ResourceId><uint name="IndexCountPerInstance">1200</uint><uint name="InstanceCount">1</uint>
  </chunk>
</capture>"""


if __name__ == "__main__":
    unittest.main()
