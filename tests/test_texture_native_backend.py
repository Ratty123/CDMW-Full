import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core import texture_native
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native


def _minimal_bc_dds(fourcc: bytes = b"DXT1", *, width: int = 4, height: int = 4, mip_count: int = 1) -> bytes:
    block_bytes = 8 if fourcc in {b"DXT1", b"ATI1", b"BC4U", b"BC4S"} else 16
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[24:28] = max(1, int(mip_count)).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = fourcc
    payload_size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block_bytes
    return b"DDS " + bytes(header) + (b"\x00" * payload_size)


def _minimal_dx10_dds(
    dxgi_format: int,
    *,
    width: int = 4,
    height: int = 4,
    mip_count: int = 1,
    bytes_per_pixel: int = 4,
) -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[24:28] = max(1, int(mip_count)).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DX10"
    dx10 = bytearray(20)
    dx10[0:4] = int(dxgi_format).to_bytes(4, "little")
    dx10[4:8] = (3).to_bytes(4, "little")
    payload_size = max(1, int(width)) * max(1, int(height)) * max(1, int(bytes_per_pixel))
    return b"DDS " + bytes(header) + bytes(dx10) + (b"\x00" * payload_size)


class NativeTextureBackendTests(unittest.TestCase):
    def test_native_texture_cache_key_includes_quality_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dds_path = Path(temp_dir) / "sample.dds"
            binary_path = Path(temp_dir) / "cd-texture.exe"
            dds_path.write_bytes(b"DDS " + b"\0" * 124)
            binary_path.write_bytes(b"fake")

            base_key = texture_native.native_texture_cache_key(
                dds_path,
                max_dimension=1024,
                slot_kind="base",
                srgb="auto",
                normal_space="auto",
                binary=binary_path,
            )
            normal_key = texture_native.native_texture_cache_key(
                dds_path,
                max_dimension=1024,
                slot_kind="normal",
                srgb="auto",
                normal_space="opengl",
                binary=binary_path,
            )
            large_key = texture_native.native_texture_cache_key(
                dds_path,
                max_dimension=4096,
                slot_kind="base",
                srgb="auto",
                normal_space="auto",
                binary=binary_path,
            )

        self.assertNotEqual(base_key, normal_key)
        self.assertNotEqual(base_key, large_key)

    def test_directxtex_cache_key_includes_backend_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "sample.dds"
            binary_path = root / "cd-texture-dx.exe"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT5"))
            binary_path.write_bytes(b"fake")

            base_key = texture_native.directxtex_texture_cache_key(
                dds_path,
                max_dimension=512,
                slot_kind="base",
                srgb="auto",
                normal_space="auto",
                binary=binary_path,
            )
            normal_key = texture_native.directxtex_texture_cache_key(
                dds_path,
                max_dimension=512,
                slot_kind="normal",
                srgb="auto",
                normal_space="opengl",
                binary=binary_path,
            )

        self.assertNotEqual(base_key, normal_key)

    def test_dds_native_parser_reads_legacy_bc_mips(self) -> None:
        info = inspect_dds_native(_minimal_bc_dds(b"DXT5", width=8, height=4, mip_count=1))

        self.assertTrue(info.supported_compressed)
        self.assertEqual("BC3_UNORM", info.format_name)
        self.assertEqual("bc3", info.compressed_family)
        self.assertEqual(1, len(info.mip_levels))
        self.assertEqual(0, info.mip_levels[0].level)
        self.assertEqual(128, info.mip_levels[0].offset)

    def test_dds_native_parser_marks_common_dx10_uncompressed_uploadable(self) -> None:
        info = inspect_dds_native(_minimal_dx10_dds(28, width=4, height=4, bytes_per_pixel=4))

        self.assertTrue(info.supported_uncompressed)
        self.assertFalse(info.supported_compressed)
        self.assertEqual("R8G8B8A8_UNORM", info.format_name)
        self.assertEqual("rgba8", info.compressed_family)
        self.assertEqual(1, info.block_width)
        self.assertEqual(1, info.block_height)
        self.assertEqual(148, info.mip_levels[0].offset)
        self.assertEqual(64, info.mip_levels[0].byte_count)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rgba.dds"
            report = dds_native_report_dict(path, info)
        self.assertTrue(report["direct_upload_candidate"])

    def test_directxtex_batch_preview_uses_one_helper_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            dds_a = root / "a.dds"
            dds_b = root / "b.dds"
            dds_a.write_bytes(_minimal_bc_dds(b"DXT1"))
            dds_b.write_bytes(_minimal_bc_dds(b"DXT5"))
            run_commands = []

            def fake_run(command, **_kwargs):
                run_commands.append(command)
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                items = []
                for item in job["jobs"]:
                    output = Path(item["output"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"\x89PNG\r\n\x1a\nfake")
                    items.append(
                        {
                            "status": "decoded",
                            "backend": "directxtex_native_0.1",
                            "source_path": item["input"],
                            "output_path": item["output"],
                            "slot": item["slot"],
                            "format": "DXGI_98",
                        }
                    )
                report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")

                class Completed:
                    returncode = 0
                    stdout = b"{}"
                    stderr = b""

                return Completed()

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.subprocess.run", side_effect=fake_run):
                    results = texture_native.ensure_directxtex_dds_preview_pngs(
                        (
                            {"dds_path": str(dds_a), "slot_kind": "base", "max_dimension": 512},
                            {"dds_path": str(dds_b), "slot_kind": "normal", "max_dimension": 512},
                        )
                    )

            self.assertEqual(1, len(run_commands))
            self.assertEqual({"batch-preview-json"}, {Path(run_commands[0][1]).name})
            self.assertEqual({str(dds_a.resolve()), str(dds_b.resolve())}, set(results))
            for preview_path in results.values():
                self.assertTrue(texture_native.native_texture_report_sidecar_path(preview_path).is_file())

    def test_report_sidecar_path_is_next_to_preview_png(self) -> None:
        sidecar = texture_native.native_texture_report_sidecar_path(Path("preview.png"))
        self.assertEqual("preview.png.cdmw_texture.json", sidecar.name)

    def test_inspect_returns_none_when_binary_missing(self) -> None:
        with patch("cdmw.core.texture_native.find_cd_texture_binary", return_value=None):
            self.assertIsNone(texture_native.inspect_dds_with_rust(Path("missing.dds")))

    def test_ensure_native_preview_writes_report_for_decoded_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "sample.dds"
            binary_path = root / "cd-texture.exe"
            dds_path.write_bytes(b"DDS " + b"\0" * 124)
            binary_path.write_bytes(b"fake")

            def fake_run(command, **_kwargs):
                output_path = Path(command[3])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

                class Completed:
                    returncode = 0
                    stdout = json.dumps(
                        {
                            "status": "decoded",
                            "backend": "cd_texture_rust_0.1",
                            "format": "BC7RgbaUnorm",
                            "slot": "base",
                            "channel_stats": {"alpha_coverage": 1.0},
                        }
                    ).encode("utf-8")
                    stderr = b""

                return Completed()

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=None):
                with patch("cdmw.core.texture_native.find_cd_texture_binary", return_value=binary_path):
                    with patch("cdmw.core.texture_native.subprocess.run", side_effect=fake_run):
                        preview_path = texture_native.ensure_native_dds_preview_png(
                            dds_path,
                            max_dimension=512,
                            slot_kind="base",
                        )

            self.assertIsNotNone(preview_path)
            report_path = texture_native.native_texture_report_sidecar_path(preview_path)
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("decoded", report["status"])
            self.assertEqual("cd_texture_rust_0.1", report["backend"])


if __name__ == "__main__":
    unittest.main()
