import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core import texture_native


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
