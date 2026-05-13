from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.constants import UPSCALE_BACKEND_NONE
from cdmw.core.common import ProcessTimeoutExpired
from cdmw.core.pipeline import rebuild_dds_files
from cdmw.models import AppConfig, TextureRule, TextureWorkflowProfile


def _write_fake_png_header(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def _fake_dds_bytes(width: int, height: int, *, mips: int = 1, fourcc: bytes = b"DXT1") -> bytes:
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4 + 0, 124)
    struct.pack_into("<I", data, 4 + 8, height)
    struct.pack_into("<I", data, 4 + 12, width)
    struct.pack_into("<I", data, 4 + 24, mips)
    struct.pack_into("<I", data, 4 + 72, 32)
    struct.pack_into("<I", data, 4 + 76, 0x4)
    data[4 + 80 : 4 + 84] = fourcc
    return bytes(data)


def _write_source_pair(root: Path) -> tuple[Path, Path, Path, Path]:
    original_root = root / "dds"
    png_root = root / "png"
    output_root = root / "out"
    texconv = root / "texconv.exe"
    original_dds = original_root / "character" / "texture" / "sample.dds"
    replacement_png = png_root / "character" / "texture" / "sample.png"
    original_dds.parent.mkdir(parents=True, exist_ok=True)
    original_dds.write_bytes(_fake_dds_bytes(64, 64, mips=7))
    _write_fake_png_header(replacement_png, 128, 128)
    texconv.write_bytes(b"fake texconv")
    return original_root, png_root, output_root, texconv


def _config(original_root: Path, png_root: Path, output_root: Path, texconv: Path) -> AppConfig:
    return AppConfig(
        original_dds_root=str(original_root),
        png_root=str(png_root),
        texture_editor_png_root="",
        dds_staging_root="",
        output_root=str(output_root),
        texconv_path=str(texconv),
        include_filters="character/texture/sample.dds",
        upscale_backend=UPSCALE_BACKEND_NONE,
        enable_dds_staging=False,
        enable_incremental_resume=False,
        csv_log_enabled=False,
        overwrite_existing_dds=True,
        workflow_profiles=(
            TextureWorkflowProfile(
                profile_id="force_rebuild",
                label="Force Rebuild",
                action_mode="rebuild_from_png",
            ),
        ),
        texture_rules=(
            TextureRule(
                pattern="*.dds",
                workflow_profile_id="force_rebuild",
            ),
        ),
    )


class TextureWorkflowGuardrailTests(unittest.TestCase):
    def test_rebuild_logs_elapsed_time_and_validates_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root, texconv = _write_source_pair(root)
            logs: list[str] = []
            timeout_values: list[float] = []

            def fake_texconv(command: list[str], **kwargs: object) -> tuple[int, str, str]:
                timeout_values.append(float(kwargs.get("timeout_seconds") or 0))
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.parent.mkdir(parents=True, exist_ok=True)
                produced.write_bytes(_fake_dds_bytes(128, 128, mips=8))
                return 0, "", ""

            with patch("cdmw.core.pipeline.run_process_with_cancellation", side_effect=fake_texconv):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root, texconv), on_log=logs.append)

            self.assertEqual(1, summary.converted)
            self.assertEqual(0, summary.failed)
            self.assertTrue((output_root / "character" / "texture" / "sample.dds").is_file())
            self.assertIn(600.0, timeout_values)
            self.assertTrue(any("BUILT character/texture/sample.dds in " in line for line in logs))

    def test_rebuild_uses_directxtex_batch_encode_before_texconv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root, texconv = _write_source_pair(root)
            native_binary = root / "cd-texture-dx.exe"
            native_binary.write_bytes(b"fake native")
            logs: list[str] = []

            def fake_encode(jobs, **_kwargs):
                results = {}
                jobs = list(jobs)
                self.assertEqual(1, len(jobs))
                output = Path(str(jobs[0]["output_path"]))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(_fake_dds_bytes(128, 128, mips=8))
                results[str(output.resolve())] = {
                    "status": "encoded",
                    "backend": "directxtex_native_0.1",
                    "output_path": str(output),
                    "encode_ms": 12.0,
                }
                return results

            with (
                patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=native_binary),
                patch("cdmw.core.texture_native.encode_dds_batch_with_directxtex", side_effect=fake_encode),
                patch("cdmw.core.pipeline._run_texture_workflow_texconv") as texconv_run,
            ):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root, texconv), on_log=logs.append)

            self.assertEqual(1, summary.converted)
            self.assertEqual(0, summary.failed)
            texconv_run.assert_not_called()
            self.assertIn("DirectXTex native batch encode", summary.results[0].note)
            self.assertTrue(any("with DirectXTex native batch" in line for line in logs))

    def test_rebuild_success_without_expected_dds_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root, texconv = _write_source_pair(root)
            logs: list[str] = []

            def fake_texconv(_command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                return 0, "", ""

            with patch("cdmw.core.pipeline.run_process_with_cancellation", side_effect=fake_texconv):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root, texconv), on_log=logs.append)

            self.assertEqual(0, summary.converted)
            self.assertEqual(1, summary.failed)
            self.assertIn("did not produce expected DDS", summary.results[0].note)
            self.assertTrue(any("FAIL character/texture/sample.dds" in line for line in logs))

    def test_rebuild_texconv_timeout_is_reported_as_file_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root, texconv = _write_source_pair(root)
            logs: list[str] = []

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                raise ProcessTimeoutExpired(command, 600)

            with patch("cdmw.core.pipeline.run_process_with_cancellation", side_effect=fake_texconv):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root, texconv), on_log=logs.append)

            self.assertEqual(0, summary.converted)
            self.assertEqual(1, summary.failed)
            self.assertIn("timed out after 600s", summary.results[0].note)
            self.assertTrue(any("texconv was terminated" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
