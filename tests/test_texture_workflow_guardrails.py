from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.constants import UPSCALE_BACKEND_NONE
from cdmw.core.common import ProcessTimeoutExpired
from cdmw.core.pipeline import rebuild_dds_files, write_csv_log
from cdmw.models import AppConfig, JobResult, TextureRule, TextureWorkflowProfile


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


def _write_source_pair(root: Path) -> tuple[Path, Path, Path]:
    original_root = root / "dds"
    png_root = root / "png"
    output_root = root / "out"
    original_dds = original_root / "character" / "texture" / "sample.dds"
    replacement_png = png_root / "character" / "texture" / "sample.png"
    original_dds.parent.mkdir(parents=True, exist_ok=True)
    original_dds.write_bytes(_fake_dds_bytes(64, 64, mips=7))
    _write_fake_png_header(replacement_png, 128, 128)
    return original_root, png_root, output_root


def _config(original_root: Path, png_root: Path, output_root: Path) -> AppConfig:
    return AppConfig(
        original_dds_root=str(original_root),
        png_root=str(png_root),
        texture_editor_png_root="",
        dds_staging_root="",
        output_root=str(output_root),
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
    def test_csv_log_serializes_slotted_job_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "build_log.csv"

            write_csv_log(
                log_path,
                [
                    JobResult(
                        original_dds="source.dds",
                        png="source.png",
                        output_dir="out",
                        width=64,
                        height=32,
                        original_mips=7,
                        used_mips=8,
                        dds_format="BC1_UNORM",
                        status="converted",
                        note="ok",
                    )
                ],
            )

            text = log_path.read_text(encoding="utf-8")
            self.assertIn("original_dds,png,output_dir,width,height", text)
            self.assertIn("source.dds,source.png,out,64,32,7,8,BC1_UNORM,converted,ok", text)

    def test_rebuild_uses_native_batch_and_validates_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root = _write_source_pair(root)
            native_binary = root / "cd-texture-dx.exe"
            native_binary.write_bytes(b"fake native")
            logs: list[str] = []

            def fake_encode(jobs: object, **_kwargs: object) -> dict[str, dict[str, object]]:
                results = {}
                jobs = list(jobs)
                self.assertEqual(1, len(jobs))
                output = Path(str(jobs[0]["output_path"]))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(_fake_dds_bytes(128, 128, mips=8))
                results[str(output.resolve())] = {
                    "status": "encoded",
                    "backend": "directxtex_native_0.2",
                    "output_path": str(output),
                    "encode_ms": 12.0,
                }
                return results

            with (
                patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=native_binary),
                patch("cdmw.core.texture_native.encode_dds_batch_with_directxtex", side_effect=fake_encode),
            ):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root), on_log=logs.append)

            self.assertEqual(1, summary.converted)
            self.assertEqual(0, summary.failed)
            self.assertTrue((output_root / "character" / "texture" / "sample.dds").is_file())
            self.assertIn("DirectXTex native batch encode", summary.results[0].note)
            self.assertTrue(any("with DirectXTex native batch" in line for line in logs))

    def test_rebuild_native_report_without_expected_dds_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root = _write_source_pair(root)
            native_binary = root / "cd-texture-dx.exe"
            native_binary.write_bytes(b"fake native")
            logs: list[str] = []

            def fake_encode(jobs: object, **_kwargs: object) -> dict[str, dict[str, object]]:
                job = list(jobs)[0]
                output = Path(str(job["output_path"]))
                return {
                    str(output.resolve()): {
                        "status": "encoded",
                        "backend": "directxtex_native_0.2",
                        "output_path": str(output),
                    }
                }

            with (
                patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=native_binary),
                patch("cdmw.core.texture_native.encode_dds_batch_with_directxtex", side_effect=fake_encode),
            ):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root), on_log=logs.append)

            self.assertEqual(0, summary.converted)
            self.assertEqual(1, summary.failed)
            self.assertIn("Native DDS encode did not produce this output", summary.results[0].note)
            self.assertTrue(any("FAIL character/texture/sample.dds" in line for line in logs))

    def test_rebuild_missing_native_helper_is_reported_as_file_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root = _write_source_pair(root)
            logs: list[str] = []

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=None):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root), on_log=logs.append)

            self.assertEqual(0, summary.converted)
            self.assertEqual(1, summary.failed)
            self.assertIn("Native DDS encode did not produce this output", summary.results[0].note)
            self.assertTrue(any("cd-texture-dx.exe is missing" in line for line in logs))

    def test_rebuild_native_timeout_is_reported_as_file_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_root, png_root, output_root = _write_source_pair(root)
            native_binary = root / "cd-texture-dx.exe"
            native_binary.write_bytes(b"fake native")
            logs: list[str] = []

            def timeout(_jobs: object, **_kwargs: object) -> dict[str, dict[str, object]]:
                raise ProcessTimeoutExpired([str(native_binary), "batch-encode-json"], 120)

            with (
                patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=native_binary),
                patch("cdmw.core.texture_native.encode_dds_batch_with_directxtex", side_effect=timeout),
            ):
                summary = rebuild_dds_files(_config(original_root, png_root, output_root), on_log=logs.append)

            self.assertEqual(0, summary.converted)
            self.assertEqual(1, summary.failed)
            self.assertIn("Native DDS encode did not produce this output", summary.results[0].note)
            self.assertTrue(any("Native DDS batch encode failed" in line for line in logs))
            self.assertTrue(any("timed out after 120s" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
