import base64
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core import texture_native
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native, inspect_dds_native_path
from cdmw.models import RunCancelled

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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


def _minimal_luminance_dds(*, width: int = 4, height: int = 4, bit_count: int = 8, mip_count: int = 1) -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = int(height).to_bytes(4, "little")
    header[12:16] = int(width).to_bytes(4, "little")
    header[24:28] = max(1, int(mip_count)).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x00020000).to_bytes(4, "little")
    header[84:88] = int(bit_count).to_bytes(4, "little")
    header[88:92] = ((1 << int(bit_count)) - 1).to_bytes(4, "little")
    payload_size = max(1, int(width)) * max(1, int(height)) * max(1, int(bit_count) // 8)
    return b"DDS " + bytes(header) + (b"\x00" * payload_size)


class NativeTextureBackendTests(unittest.TestCase):
    def test_directxtex_helper_contains_structured_cxx_exception_boundaries(self) -> None:
        source = Path("native/cd_texture_dx/src/main.cpp").read_text(encoding="utf-8")

        self.assertNotIn("#include <regex>", source)
        self.assertNotIn("std::regex", source)
        self.assertIn("json_leaf_objects", source)
        self.assertIn("json_parser_self_test", source)
        self.assertIn(r"\u00e9", source)
        self.assertIn(r"\ud83d\udde1", source)
        self.assertIn("decode_preview_guarded", source)
        self.assertIn("encode_dds_guarded", source)
        self.assertIn("batch_preview_json_guarded", source)
        self.assertIn("batch_encode_json_guarded", source)
        self.assertIn("write_batch_exception_report", source)
        self.assertIn('"batch_preview_item_exception"', source)
        self.assertIn('"batch_encode_item_exception"', source)
        self.assertIn('"native_cxx_exception_caught"', source)
        self.assertIn("return run_command(argc, argv);", source)
        self.assertIn("catch (const std::exception& exc)", source)

    def test_directxtex_fetchcontent_builds_from_cached_source_offline(self) -> None:
        for relative in (
            "native/cd_texture_dx/CMakeLists.txt",
            "native/cdmw_d3d11_preview/CMakeLists.txt",
        ):
            with self.subTest(relative=relative):
                source = Path(relative).read_text(encoding="utf-8")

                self.assertIn("GIT_REPOSITORY https://github.com/microsoft/DirectXTex.git", source)
                self.assertIn("UPDATE_DISCONNECTED TRUE", source)
        build_source = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Save-DirectXTexDependencyCache", build_source)
        self.assertIn("build\\native-deps", build_source)
        self.assertIn("-DFETCHCONTENT_SOURCE_DIR_DIRECTXTEX=", build_source)
        self.assertIn("-DFETCHCONTENT_UPDATES_DISCONNECTED=ON", build_source)

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
                normal_space="green_up",
                binary=binary_path,
            )

        self.assertNotEqual(base_key, normal_key)

    def test_directxtex_preview_defer_env_skips_helper_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dds_path = Path(temp_dir) / "sample.dds"
            dds_path.write_bytes(_minimal_bc_dds())
            with (
                patch.dict(texture_native.os.environ, {"CDMW_DEFER_TEXTURE_PREVIEW": "1"}),
                patch.object(texture_native, "find_directxtex_texture_binary", side_effect=AssertionError("helper should not be queried")),
            ):
                result = texture_native.ensure_directxtex_dds_preview_pngs(
                    [{"dds_path": str(dds_path), "slot_kind": "base"}]
                )

        self.assertEqual({}, result)

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

    def test_dds_native_parser_reads_texture_editor_export_formats(self) -> None:
        cases = (
            (inspect_dds_native(_minimal_bc_dds(b"DXT1")), "BC1_UNORM", "bc1"),
            (inspect_dds_native(_minimal_bc_dds(b"DXT5")), "BC3_UNORM", "bc3"),
            (inspect_dds_native(_minimal_bc_dds(b"ATI2")), "BC5_UNORM", "bc5"),
            (inspect_dds_native(_minimal_dx10_dds(98, bytes_per_pixel=16)), "BC7_UNORM", "bc7"),
            (inspect_dds_native(_minimal_dx10_dds(28, bytes_per_pixel=4)), "R8G8B8A8_UNORM", "rgba8"),
            (inspect_dds_native(_minimal_dx10_dds(61, bytes_per_pixel=1)), "R8_UNORM", "r8"),
            (inspect_dds_native(_minimal_dx10_dds(56, bytes_per_pixel=2)), "R16_UNORM", "r16"),
            (inspect_dds_native(_minimal_luminance_dds(bit_count=8)), "R8_UNORM", "r8"),
            (inspect_dds_native(_minimal_luminance_dds(bit_count=16)), "R16_UNORM", "r16"),
        )

        for info, format_name, family in cases:
            self.assertEqual(format_name, info.format_name)
            self.assertEqual(family, info.compressed_family)
            self.assertTrue(info.supported_compressed or info.supported_uncompressed)

    def test_dds_native_path_inspects_header_without_reading_full_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large.dds"
            path.write_bytes(_minimal_bc_dds(b"DXT5", width=4096, height=4096, mip_count=1) + (b"x" * 1024))

            with patch.object(Path, "read_bytes", side_effect=AssertionError("full DDS read")):
                info = inspect_dds_native_path(path)

        self.assertTrue(info.supported_compressed)
        self.assertEqual("BC3_UNORM", info.format_name)

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
                self.assertIn("timeout_seconds", _kwargs)
                self.assertNotIn("timeout", _kwargs)
                run_commands.append(command)
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                items = []
                for item in job["jobs"]:
                    output = Path(item["output"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(_MINIMAL_PNG)
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

                return 0, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    results = texture_native.ensure_directxtex_dds_preview_pngs(
                        (
                            {"dds_path": str(dds_a), "slot_kind": "base", "max_dimension": 512},
                            {"dds_path": str(dds_b), "slot_kind": "normal", "max_dimension": 512},
                        )
                    )

            self.assertEqual(1, len(run_commands))
            self.assertEqual({"batch-preview-json"}, {Path(run_commands[0][1]).name})
            self.assertFalse(Path(run_commands[0][2]).parent.exists())
            self.assertEqual({str(dds_a.resolve()), str(dds_b.resolve())}, set(results))
            for preview_path in results.values():
                self.assertTrue(texture_native.native_texture_report_sidecar_path(preview_path).is_file())

    def test_directxtex_batch_preview_records_structured_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            dds_path = root / "failed.dds"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT1"))
            texture_native.directxtex_texture_failure_reports(clear=True)

            def fake_run(_command, **_kwargs):
                return 1, "", "decode failed: unsupported data"

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    results = texture_native.ensure_directxtex_dds_preview_pngs(
                        ({"dds_path": str(dds_path), "slot_kind": "base", "max_dimension": 512},)
                    )

            reports = texture_native.directxtex_texture_failure_reports(clear=True)

        self.assertEqual({}, results)
        self.assertTrue(reports)
        self.assertEqual("failed", reports[-1]["status"])
        self.assertEqual("directxtex", reports[-1]["backend"])
        self.assertEqual("batch-preview-json", reports[-1]["operation"])
        self.assertEqual(1, reports[-1]["returncode"])
        self.assertIn("decode failed", reports[-1]["stderr_summary"])
        self.assertTrue(reports[-1]["fallback_available"])

    def test_texconv_preview_report_unknown_metadata_is_not_clean_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "unknown.dds"
            preview_path = root / "unknown.png"
            dds_path.write_bytes(b"not a valid dds")
            preview_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            with patch("cdmw.core.texture_native.inspect_dds_native_path", side_effect=ValueError("bad header")):
                report = texture_native.texconv_preview_report(dds_path, preview_path)

        self.assertEqual("decoded_with_unknown_metadata", report["status"])
        self.assertFalse(report["metadata_verified"])
        self.assertEqual("", report["format"])
        self.assertEqual(0, report["width"])
        self.assertEqual(0, report["height"])

    def test_directxtex_batch_encode_uses_one_helper_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            png_a = root / "a.png"
            png_b = root / "b.png"
            png_a.write_bytes(b"\x89PNG\r\n\x1a\nfake-a")
            png_b.write_bytes(b"\x89PNG\r\n\x1a\nfake-b")
            output_a = root / "out" / "a.dds"
            output_b = root / "out" / "b.dds"
            run_commands = []

            def fake_run(command, **_kwargs):
                run_commands.append(command)
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                self.assertEqual("directxtex_native_0.1", job["backend"])
                items = []
                for item in job["jobs"]:
                    output = Path(item["output"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"DDS fake")
                    items.append(
                        {
                            "status": "encoded",
                            "backend": "directxtex_native_0.1",
                            "native_backend": "directxtex",
                            "source_path": item["input"],
                            "output_path": item["output"],
                            "format": item["format"],
                            "width": item["width"],
                            "height": item["height"],
                            "mip_count": item["mip_count"],
                        }
                    )
                report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")

                return 0, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    results = texture_native.encode_dds_batch_with_directxtex(
                        (
                            {
                                "png_path": str(png_a),
                                "output_path": str(output_a),
                                "format": "BC7_UNORM",
                                "width": 256,
                                "height": 256,
                                "mip_count": 4,
                            },
                            {
                                "png_path": str(png_b),
                                "output_path": str(output_b),
                                "format": "BC5_UNORM",
                                "width": 128,
                                "height": 128,
                                "mip_count": 1,
                            },
                        )
                    )

            self.assertEqual(1, len(run_commands))
            self.assertEqual({"batch-encode-json"}, {Path(run_commands[0][1]).name})
            self.assertFalse(Path(run_commands[0][2]).parent.exists())
            self.assertEqual({str(output_a.resolve()), str(output_b.resolve())}, set(results))
            self.assertEqual("BC7_UNORM", results[str(output_a.resolve())]["format"])
            self.assertEqual(4, results[str(output_a.resolve())]["mip_count"])

    def test_directxtex_batch_encode_covers_editor_formats_overwrite_false_and_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            png_path = root / "source.png"
            png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            formats = ("BC1_UNORM", "BC3_UNORM", "BC5_UNORM", "BC7_UNORM", "R8G8B8A8_UNORM", "UNSUPPORTED_FORMAT")
            seen_jobs = []

            def fake_run(command, **_kwargs):
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                seen_jobs.extend(job["jobs"])
                items = []
                for item in job["jobs"]:
                    output = Path(item["output"])
                    if item["format"] == "UNSUPPORTED_FORMAT":
                        items.append(
                            {
                                "status": "error",
                                "backend": "directxtex_native_0.1",
                                "source_path": item["input"],
                                "output_path": item["output"],
                                "message": "unsupported DDS format UNSUPPORTED_FORMAT",
                            }
                        )
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"DDS fake")
                    items.append(
                        {
                            "status": "encoded",
                            "backend": "directxtex_native_0.1",
                            "native_backend": "directxtex",
                            "source_path": item["input"],
                            "output_path": item["output"],
                            "format": item["format"],
                            "mip_count": item["mip_count"],
                        }
                    )
                report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")
                return 2, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    results = texture_native.encode_dds_batch_with_directxtex(
                        tuple(
                            {
                                "png_path": str(png_path),
                                "output_path": str(root / "out" / f"{format_name}.dds"),
                                "format": format_name,
                                "mip_count": 4,
                                "overwrite": format_name != "BC1_UNORM",
                            }
                            for format_name in formats
                        )
                    )

        self.assertEqual(list(formats), [job["format"] for job in seen_jobs])
        self.assertFalse(seen_jobs[0]["overwrite"])
        self.assertNotIn(str((root / "out" / "UNSUPPORTED_FORMAT.dds").resolve()), results)
        self.assertEqual(len(formats) - 1, len(results))

    def test_directxtex_decode_preview_writes_supplied_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            dds_path = root / "sample.dds"
            preview_path = root / "preview" / "sample.png"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT5"))

            def fake_run(command, **_kwargs):
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                item = job["jobs"][0]
                self.assertNotEqual(str(preview_path.resolve()), item["output"])
                self.assertEqual((root / "temp").resolve(), Path(item["output"]).parent.parent)
                Path(item["output"]).parent.mkdir(parents=True, exist_ok=True)
                Path(item["output"]).write_bytes(_MINIMAL_PNG)
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "items": [
                                {
                                    "status": "decoded",
                                    "backend": "directxtex_native_0.1",
                                    "native_backend": "directxtex",
                                    "source_path": item["input"],
                                    "output_path": item["output"],
                                    "format": "BC3_UNORM",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return 0, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    report = texture_native.decode_dds_preview_with_directxtex(
                        dds_path,
                        preview_path,
                        max_dimension=512,
                        temp_root=root / "temp",
                    )
            preview_exists = preview_path.is_file()
            sidecar_exists = texture_native.native_texture_report_sidecar_path(preview_path).is_file()

        self.assertIsNotNone(report)
        self.assertTrue(preview_exists)
        self.assertTrue(sidecar_exists)

    def test_directxtex_batch_preview_can_return_per_slot_job_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            dds_path = root / "shared.dds"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT1"))

            def fake_run(command, **_kwargs):
                self.assertIn("timeout_seconds", _kwargs)
                self.assertNotIn("timeout", _kwargs)
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                items = []
                for item in job["jobs"]:
                    output = Path(item["output"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(_MINIMAL_PNG)
                    items.append(
                        {
                            "status": "decoded",
                            "backend": "directxtex_native_0.1",
                            "source_path": item["input"],
                            "output_path": item["output"],
                            "slot": item["slot"],
                        }
                    )
                report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")

                return 0, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
                    results = texture_native.ensure_directxtex_dds_preview_pngs(
                        (
                            {"dds_path": str(dds_path), "slot_kind": "base", "max_dimension": 512},
                            {
                                "dds_path": str(dds_path),
                                "slot_kind": "normal",
                                "max_dimension": 192,
                                "normal_space": "green_up",
                            },
                        ),
                        include_job_keys=True,
                    )

            base_key = texture_native.directxtex_preview_result_key(dds_path, max_dimension=512, slot_kind="base")
            normal_key = texture_native.directxtex_preview_result_key(
                dds_path,
                max_dimension=192,
                slot_kind="normal",
                normal_space="green_up",
            )
            self.assertIn(str(dds_path.resolve()), results)
            self.assertIn(base_key, results)
            self.assertIn(normal_key, results)
            self.assertNotEqual(results[base_key], results[normal_key])

    def test_directxtex_batch_preview_honors_cancel_before_helper_launch(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "cd-texture-dx.exe"
            binary_path.write_bytes(b"fake")
            dds_path = root / "cancel.dds"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT1"))
            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation") as run_mock:
                    with self.assertRaises(RunCancelled):
                        texture_native.ensure_directxtex_dds_preview_pngs(
                            ({"dds_path": str(dds_path), "slot_kind": "base", "max_dimension": 512},),
                            stop_event=stop_event,
                        )
            run_mock.assert_not_called()

    def test_report_sidecar_path_is_next_to_preview_png(self) -> None:
        sidecar = texture_native.native_texture_report_sidecar_path(Path("preview.png"))
        self.assertEqual("preview.png.cdmw_texture.json", sidecar.name)

    def test_ensure_native_preview_uses_directxtex_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dds_path = root / "sample.dds"
            binary_path = root / "cd-texture-dx.exe"
            dds_path.write_bytes(_minimal_bc_dds(b"DXT5"))
            binary_path.write_bytes(b"fake")

            def fake_run(command, **_kwargs):
                job_path = Path(command[2])
                report_path = Path(command[3])
                job = json.loads(job_path.read_text(encoding="utf-8"))
                items = []
                for item in job["jobs"]:
                    output_path = Path(item["output"])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(_MINIMAL_PNG)
                    items.append(
                        {
                            "status": "decoded",
                            "backend": "directxtex_native_0.1",
                            "native_backend": "directxtex",
                            "source_path": item["input"],
                            "output_path": item["output"],
                            "format": "BC3_UNORM",
                            "slot": item["slot"],
                        }
                    )
                report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")
                return 0, "{}", ""

            with patch("cdmw.core.texture_native.find_directxtex_texture_binary", return_value=binary_path):
                with patch("cdmw.core.texture_native.run_process_with_cancellation", side_effect=fake_run):
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
            self.assertEqual("directxtex_native_0.1", report["backend"])


if __name__ == "__main__":
    unittest.main()
