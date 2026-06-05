from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core import archive as archive_core
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings, RunCancelled
from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_core import (
    NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES,
    NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS,
    NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES,
    NativePreviewCoreServiceClient,
    build_native_preview_core_job,
    prune_native_preview_core_cache,
    run_native_preview_core_preview_job,
)
from cdmw.rendering.native_preview_package_cache import (
    create_native_preview_package_staging_dir,
    lookup_native_preview_package_cache,
    native_preview_package_cache_budget,
    store_native_preview_package_cache,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/example/cd_example.pac",
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/1.paz"),
        offset=128,
        comp_size=64,
        orig_size=64,
        flags=0,
        paz_index=1,
    )


def _minimal_dds_header(
    *,
    compressed_size: int,
    decompressed_size: int,
    width: int = 4,
    height: int = 4,
    fourcc: bytes = b"DXT1",
) -> bytes:
    header = bytearray(128)
    header[:4] = b"DDS "
    header[4:8] = (124).to_bytes(4, "little")
    header[12:16] = int(height).to_bytes(4, "little")
    header[16:20] = int(width).to_bytes(4, "little")
    header[20:24] = int(decompressed_size).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[28:32] = (1).to_bytes(4, "little")
    header[32:36] = int(compressed_size).to_bytes(4, "little")
    header[36:40] = int(decompressed_size).to_bytes(4, "little")
    header[76:80] = (32).to_bytes(4, "little")
    header[80:84] = (4).to_bytes(4, "little")
    header[84:88] = fourcc
    return bytes(header)


class _FakeServiceStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        return


class _FakeServiceProcess:
    def __init__(self) -> None:
        self.stdin = _FakeServiceStdin()
        self.stdout = object()
        self.alive = True
        self.killed = False

    def poll(self) -> object:
        return None if self.alive else 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.alive = False
        return 0

    def kill(self) -> None:
        self.killed = True
        self.alive = False


class NativePreviewCoreTests(unittest.TestCase):
    def test_build_job_carries_archive_entry_and_schema_v8(self) -> None:
        job = build_native_preview_core_job(
            _entry(),
            cache_root=Path("C:/cache/native"),
            output_root=Path("C:/cache/package"),
            render_settings=ModelPreviewRenderSettings(),
            package_root=Path("C:/game"),
        )

        self.assertEqual(8, job["schema_version"])
        self.assertEqual("d3d11", job["renderer_backend"])
        self.assertEqual("character/model/example/cd_example.pac", job["entry"]["path"])
        self.assertEqual("C:\\game\\0009\\1.paz", job["entry"]["paz_file"])
        self.assertEqual("mesh_base_first", job["render_settings"]["visible_texture_mode"])
        self.assertEqual("lit", job["render_settings"]["render_diagnostic_mode"])
        self.assertEqual("lit", job["render_settings"]["d3d11_view_mode"])
        self.assertAlmostEqual(-0.85, job["render_settings"]["d3d11_mip_lod_bias"])
        self.assertEqual("asset", job["render_settings"]["d3d11_normal_y_mode"])
        self.assertEqual("wrap", job["render_settings"]["d3d11_texture_address_mode"])
        self.assertTrue(job["capabilities"]["direct_dds"])
        self.assertTrue(job["capabilities"]["d3d11_package"])
        self.assertTrue(job["capabilities"]["material_graph"])
        self.assertEqual(3, job["capabilities"]["material_graph_version"])
        self.assertFalse(job["capabilities"]["python_fallback_allowed"])
        self.assertTrue(job["capabilities"]["native_material_runtime"])

    def test_archive_d3d11_preview_is_native_cpp_only_when_core_is_enabled(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        worker_start = source.index("class ArchivePreviewWorker")
        worker_end = source.index("class ArchiveNativePreviewPrefetchWorker", worker_start)
        worker_source = source[worker_start:worker_end]
        emit_start = worker_source.index("def _emit_native_preview_core_attempt")
        emit_end = worker_source.index("def _emit_preview_payload", emit_start)
        emit_source = worker_source[emit_start:emit_end]
        fast_start = worker_source.index("def _should_emit_progressive_fast_preview")
        fast_end = worker_source.index("def _native_preview_core_supported_for_entry", fast_start)
        fast_source = worker_source[fast_start:fast_end]

        self.assertIn("native_attempt = self._try_native_preview_core()", worker_source)
        self.assertIn("if self._emit_native_preview_core_attempt(native_attempt, timings):", worker_source)
        self.assertIn("return", worker_source)
        self.assertIn("if self.native_preview_core_enabled:", emit_source)
        self.assertIn("payload = self._native_preview_core_failure_result(native_attempt, timings)", emit_source)
        self.assertIn("return True", emit_source)
        self.assertIn("if self._native_preview_core_supported_for_entry():", fast_source)
        self.assertIn("return False", fast_source)

    def test_missing_binary_returns_fallback_attempt(self) -> None:
        with patch.object(native_preview_core, "find_native_preview_core_binary", return_value=None):
            attempt = run_native_preview_core_preview_job(
                _entry(),
                cache_root=Path("C:/cache/native"),
                timeout_seconds=0.5,
            )

        self.assertEqual("missing", attempt.status)
        self.assertFalse(attempt.succeeded)
        self.assertIn("unavailable", attempt.diagnostic_line())

    def test_partial_dds_reconstruction_prefers_payload_chunk_table_when_pathc_is_stale(self) -> None:
        entry = _entry()
        pathc_header = _minimal_dds_header(compressed_size=64, decompressed_size=4)
        payload_header = _minimal_dds_header(compressed_size=4, decompressed_size=4)
        with patch.object(archive_core, "get_archive_partial_dds_header", return_value=pathc_header):
            rebuilt = archive_core.reconstruct_partial_dds(entry, payload_header + b"ABCD")

        self.assertEqual(pathc_header + b"ABCD", rebuilt)

    def test_report_success_returns_package_path(self) -> None:
        def fake_run_process(cmd, **_kwargs):
            report_path = Path(cmd[3])
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "package_path": "C:/cache/native/package_001",
                        "backend": "cdmw_preview_core_0.1",
                        "decoded_cache_job_hits": 2,
                        "decoded_cache_job_misses": 1,
                    }
                ),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_binary = Path(temp_dir) / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=Path(temp_dir) / "cache",
                    timeout_seconds=0.5,
                    use_service=False,
                )

        self.assertTrue(attempt.succeeded)
        self.assertEqual("C:/cache/native/package_001", attempt.package_path)
        self.assertIn("cache=2/1", attempt.diagnostic_line())

    def test_cancel_after_service_dispatch_leaves_job_file_for_native_service(self) -> None:
        class _CancellingService:
            def preview_job(self, job_path, report_path, *, timeout_seconds, stop_event=None, on_dispatched=None):
                del report_path, timeout_seconds, stop_event
                self.job_path = Path(job_path)
                if on_dispatched is not None:
                    on_dispatched()
                raise RunCancelled("cancelled after dispatch")

            @property
            def process_id(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_binary = temp_path / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            job_root = temp_path / "job_root"
            job_root.mkdir()
            service = _CancellingService()
            diagnostic_log = temp_path / "native_events.jsonl"

            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core.tempfile, "mkdtemp", return_value=str(job_root)),
                patch.object(native_preview_core, "_get_native_preview_core_service", return_value=service),
                self.assertRaises(RunCancelled),
            ):
                run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=temp_path / "cache",
                    timeout_seconds=0.5,
                    diagnostic_log=diagnostic_log,
                )

            self.assertTrue((job_root / "job.json").is_file())
            self.assertIn("native_preview_core_cancel_after_dispatch", diagnostic_log.read_text(encoding="utf-8"))

    def test_native_preview_core_is_bundled_and_archive_worker_attempts_it(self) -> None:
        spec_text = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        build_text = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        main_window_text = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        source_text = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        d3d11_text = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("cdmw-preview-core.exe", spec_text)
        self.assertIn("native\\cdmw_preview_core", build_text)
        self.assertIn("run_native_preview_core_preview_job", main_window_text)
        self.assertIn("native_preview_core_enabled", main_window_text)
        self.assertIn("_validate_d3d11_preview_package_paths", main_window_text)
        self.assertIn('descriptor.get("available", True)', main_window_text)
        self.assertIn('descriptor.get("direct_upload_candidate", True)', main_window_text)
        self.assertIn("renderer:", main_window_text)
        self.assertIn("d3d11_renderer_start_blocked_invalid_package", main_window_text)
        self.assertIn("preview-job", source_text)
        self.assertIn("name-index-job", source_text)
        self.assertIn("--service", source_text)
        self.assertIn('\\"exit_code\\"', source_text)
        self.assertIn('\\"report_path\\"', source_text)
        self.assertNotIn("std::cout << read_text(fs::path(report_path))", source_text)
        self.assertIn("native_diagnostics.h", source_text)
        self.assertIn("--diagnostic-log", source_text)
        self.assertIn("--crash-dir", source_text)
        self.assertIn("preview_job_start", source_text)
        self.assertIn("service_start", source_text)
        self.assertIn("_native_diagnostic_args", Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8"))
        self.assertIn("parse_pac_submeshes", source_text)
        self.assertIn("crypt_chacha20_filename", source_text)
        self.assertIn("lz4_decompress_block", source_text)
        self.assertIn("dds_textures", source_text)
        self.assertIn("parse_pam_submeshes", source_text)
        self.assertIn("parse_pamlod_submeshes", source_text)
        self.assertIn("material_sidecars", source_text)
        self.assertIn("native_sidecar_index", source_text)
        self.assertIn("shader_rule_for_family", source_text)
        self.assertIn("role_from_parameter_shader_and_name", source_text)
        self.assertIn("packed_channels_for_role", source_text)
        self.assertIn("texture_flip_vertical", source_text)
        self.assertIn("job.flip_texture_v", source_text)
        self.assertIn("user_flip_v", source_text)
        self.assertIn('"flip_texture_v"', Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8"))
        self.assertIn("legacy_no_flip", source_text)
        self.assertIn("support_role_requires_material_scope", source_text)
        self.assertIn("rejected_texture_examples", source_text)
        self.assertIn("skin/hair visible layer albedo held", source_text)
        self.assertIn("shader_rule_holds_layer_albedo", source_text)
        self.assertIn("material_output_quality", source_text)
        self.assertIn("decoded_cache_job_hits", source_text)
        self.assertIn("prune_decoded_entry_cache", source_text)
        self.assertIn("kDecodedEntryCacheMaxEntries = 512", source_text)
        self.assertIn("kDecodedEntryCacheMaxBytes = 256ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheMaxSingleBytes = 64ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheRecycleBytes = 192ull * 1024ull * 1024ull", source_text)
        self.assertIn("kServiceMaxJobs = 32", source_text)
        self.assertIn("kServicePrivateRecycleBytes = 768ull * 1024ull * 1024ull", source_text)
        self.assertIn("process_private_bytes", source_text)
        self.assertIn("service_recycle_reason", source_text)
        python_source = Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8")
        self.assertIn("_get_native_preview_core_service", python_source)
        self.assertIn("def process_id", python_source)
        self.assertIn("native_preview_core_process_pid", python_source)
        self.assertIn("sampler_max_anisotropy", d3d11_text)
        self.assertIn("stats_.sampler_max_anisotropy = std::clamp(render_tuning_.max_anisotropy, 1, 16)", d3d11_text)
        self.assertIn("d3d11_mip_lod_bias", d3d11_text)
        self.assertIn("stats_.sampler_mip_lod_bias = std::clamp(render_tuning_.mip_lod_bias, -2.0f, 1.0f)", d3d11_text)
        self.assertIn("const bool replacing_existing_sampler = static_cast<bool>(sampler_)", d3d11_text)
        self.assertIn("if (replacing_existing_sampler)", d3d11_text)
        self.assertIn("D3D11_TEXTURE_ADDRESS_CLAMP", d3d11_text)
        self.assertIn("D3D11_CULL_BACK", d3d11_text)
        self.assertIn("d3d11_light_azimuth_degrees", d3d11_text)
        self.assertIn("d3d11_normal_y_mode", d3d11_text)
        self.assertIn("d3d11_environment_strength", d3d11_text)
        self.assertIn("diffuse_wrap_bias", d3d11_text)
        self.assertIn('"diffuse_wrap_bias": float(getattr(settings, "diffuse_wrap_bias", 0.72) or 0.72)', Path("cdmw/ui/native_d3d11_preview_host.py").read_text(encoding="utf-8"))
        self.assertIn("sampler_recreate_count", d3d11_text)
        self.assertIn('\\"sampler_mip_lod_bias\\"', d3d11_text)
        self.assertIn('\\"sampler_recreate_count\\"', d3d11_text)

    def test_preview_core_service_recycles_after_job_count_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            active_report = [temp_path / "report.json"]

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                active_report[0].write_text(
                    json.dumps({"status": "ok", "decoded_cache_bytes": 0, "process_private_bytes": 0}),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                for index in range(NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS):
                    active_report[0] = temp_path / f"report_{index}.json"
                    client.preview_job(temp_path / "job.json", active_report[0], timeout_seconds=0.5)

            report = json.loads(active_report[0].read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("job_count", report["service_recycle_reason"])
            self.assertEqual(NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS, report["service_job_count"])
            self.assertTrue(any('"shutdown"' in write for write in fake_process.stdin.writes))

    def test_preview_core_service_recycles_when_binary_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            binary = temp_path / "cdmw-preview-core.exe"
            binary.write_text("old", encoding="utf-8")
            old_client = NativePreviewCoreServiceClient(binary)
            old_client._process = _FakeServiceProcess()

            previous_service = native_preview_core._native_preview_core_service
            try:
                native_preview_core._native_preview_core_service = old_client
                binary.write_text("new-build", encoding="utf-8")

                new_client = native_preview_core._get_native_preview_core_service(binary)

                self.assertIsNot(new_client, old_client)
                self.assertIsNone(old_client._process)
                self.assertEqual(
                    NativePreviewCoreServiceClient.resolve_binary_signature(binary),
                    new_client.binary_signature,
                )
            finally:
                native_preview_core._native_preview_core_service = previous_service

    def test_preview_core_service_recycles_after_decoded_cache_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            report_path = temp_path / "report.json"

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "decoded_cache_bytes": NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES + 1,
                            "process_private_bytes": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                client.preview_job(temp_path / "job.json", report_path, timeout_seconds=0.5)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("decoded_cache_bytes", report["service_recycle_reason"])

    def test_preview_core_service_recycles_after_private_memory_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            report_path = temp_path / "report.json"

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "decoded_cache_bytes": 0,
                            "process_private_bytes": NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES + 1,
                        }
                    ),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                client.preview_job(temp_path / "job.json", report_path, timeout_seconds=0.5)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("process_private_bytes", report["service_recycle_reason"])

    def test_preview_core_service_recovers_invalid_stdout_when_report_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            report_path = temp_path / "report.json"

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                report_path.write_text(
                    json.dumps({"status": "ok", "package_path": "C:/cache/package"}),
                    encoding="utf-8",
                )
                return '-wrapper candidate cd_texturelayer_001_0018_n.dds"],"notes":[]}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                client.preview_job(temp_path / "job.json", report_path, timeout_seconds=0.5)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("invalid_stdout_response", report["service_recycle_reason"])
            self.assertTrue(any('"shutdown"' in write for write in fake_process.stdin.writes))

    def test_archive_preview_worker_owns_native_preview_core_helpers(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        archive_worker_start = source.index("class ArchivePreviewWorker(QObject):")
        d3d11_worker_start = source.index("class ArchiveD3D11PackageWorker(QObject):")
        archive_worker_source = source[archive_worker_start:d3d11_worker_start]
        d3d11_worker_source = source[d3d11_worker_start:source.index("class AlignmentD3D11PackageWorker(QObject):")]

        self.assertIn("def _try_native_preview_core", archive_worker_source)
        self.assertIn("def _native_preview_core_result", archive_worker_source)
        self.assertIn("def _attach_native_preview_core_note", archive_worker_source)
        self.assertNotIn("def _try_native_preview_core", d3d11_worker_source)
        self.assertNotIn("self._try_native_preview_core()", d3d11_worker_source)

    def test_archive_browser_has_native_preview_prefetch_worker(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("class ArchiveNativePreviewPrefetchWorker(QObject):", source)
        self.assertIn('NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod"}', source)
        self.assertNotIn('not in ARCHIVE_MODEL_EXTENSIONS:\n                return None', source)
        self.assertIn("archive_native_prefetch_timer", source)
        self.assertIn("def _archive_native_prefetch_candidate_entries", source)
        self.assertIn("def _start_archive_native_preview_prefetch", source)
        self.assertIn("def _stop_archive_native_preview_prefetch", source)
        self.assertIn("archive_native_prefetch_thread", source)
        self.assertIn("timeout_seconds=5.0", source)
        self.assertIn("run_native_preview_core_preview_job", source)
        self.assertIn("self._native_preview_package_cache_mode() != \"aggressive\"", source)
        self.assertIn("native_preview_package_prefetch_limit", source)
        self.assertIn("store_native_preview_package_cache", source)
        self.assertIn("create_native_preview_package_staging_dir", source)
        self.assertNotIn('f"_staging_{self.native_preview_package_cache_key}', source)
        self.assertNotIn('f"_staging_prefetch_{key}', source)

    def test_native_preview_package_staging_dir_uses_short_prunable_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "native_preview_core"
            staging = create_native_preview_package_staging_dir(cache_root)

            self.assertEqual(cache_root / "packages", staging.parent)
            self.assertTrue(staging.name.startswith("_staging_"))
            self.assertLessEqual(len(staging.name), 32)

    def test_native_preview_package_cache_promotes_and_validates_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            staging = cache_root / "packages" / "_staging_key"
            package = staging / "package"
            package.mkdir(parents=True)
            (package / "manifest.json").write_text('{"schema_version":8,"batches":[]}', encoding="utf-8")

            def validate(path: Path):
                return (path / "manifest.json").is_file(), ()

            max_bytes, target_bytes = native_preview_package_cache_budget("balanced")
            hit = store_native_preview_package_cache(
                cache_root,
                "abc",
                staging,
                {"source": "test"},
                validate_package=validate,
                max_bytes=max_bytes,
                target_bytes=target_bytes,
            )

            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertTrue((hit.package_dir / "manifest.json").is_file())
            self.assertFalse(staging.exists())
            second_hit = lookup_native_preview_package_cache(cache_root, "abc", validate_package=validate)
            self.assertIsNotNone(second_hit)

    def test_native_preview_package_cache_keeps_new_package_when_over_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            staging = cache_root / "packages" / "_staging_big"
            package = staging / "package"
            package.mkdir(parents=True)
            (package / "manifest.json").write_text('{"schema_version":8,"batches":[]}', encoding="utf-8")
            (package / "payload.bin").write_bytes(b"x" * 64)

            def validate(path: Path):
                return (path / "manifest.json").is_file(), ()

            hit = store_native_preview_package_cache(
                cache_root,
                "big",
                staging,
                {"source": "test"},
                validate_package=validate,
                max_bytes=1,
                target_bytes=0,
            )

            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertTrue((hit.package_dir / "manifest.json").is_file())

    def test_run_native_preview_core_job_accepts_durable_output_root(self) -> None:
        captured_output_roots: list[str] = []

        def fake_run_process(cmd, **_kwargs):
            report_path = Path(cmd[3])
            job = json.loads(Path(cmd[2]).read_text(encoding="utf-8"))
            captured_output_roots.append(job["output_root"])
            report_path.write_text(
                json.dumps({"status": "ok", "package_path": job["output_root"]}),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_binary = temp_path / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            output_root = temp_path / "durable" / "package"
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=temp_path / "cache",
                    output_root=output_root,
                    timeout_seconds=0.5,
                    use_service=False,
                )

        self.assertTrue(attempt.succeeded)
        self.assertEqual(str(output_root), attempt.package_path)
        self.assertEqual([str(output_root)], captured_output_roots)

    def test_run_native_preview_core_repairs_metal_manifest_contract(self) -> None:
        def fake_run_process(cmd, **_kwargs):
            report_path = Path(cmd[3])
            job = json.loads(Path(cmd[2]).read_text(encoding="utf-8"))
            package = Path(job["output_root"])
            package.mkdir(parents=True)
            (package / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 8,
                        "backend": "d3d11",
                        "render_diagnostic_mode": "lit",
                        "d3d11_view_mode": "lit",
                        "batches": [
                            {
                                "index": 0,
                                "material_name": "CD_PHM_Gold_Armor",
                                "material_category": "metal",
                                "material_category_confidence": 0.95,
                                "material_category_reason": "metal:armor_family_material_response",
                                "material_response_disposition": "specular_gloss_metal_response",
                                "dds_textures": {"material": {"source_path": "cd_temp_r_m.dds"}},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps({"status": "ok", "package_path": str(package)}),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_binary = temp_path / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            output_root = temp_path / "package"
            settings = ModelPreviewRenderSettings(diffuse_wrap_bias=0.91)
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=temp_path / "cache",
                    output_root=output_root,
                    render_settings=settings,
                    timeout_seconds=0.5,
                    use_service=False,
                )

            manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))

        self.assertTrue(attempt.succeeded)
        self.assertEqual(2, manifest["material_contract_schema"])
        self.assertEqual(2, manifest["material_channel_contract_schema"])
        self.assertEqual(1, manifest["texture_quality_schema"])
        self.assertEqual("shiny_metal_inspection", manifest["lighting_preset"])
        self.assertAlmostEqual(0.91, manifest["diffuse_wrap_bias"])
        batch = manifest["batches"][0]
        self.assertGreaterEqual(batch["metalness"], 0.68)
        self.assertGreaterEqual(batch["specular"], 0.68)
        self.assertLessEqual(batch["roughness"], 0.24)
        self.assertEqual(2, batch["material_contract"]["schema_version"])
        self.assertEqual(2, batch["material_channel_contract"]["schema_version"])
        self.assertGreaterEqual(batch["material_contract"]["pbr_scalar_hints"]["metalness"], 0.68)
        self.assertEqual(1, attempt.diagnostics["native_preview_core_repaired_metal_batches"])

    def test_native_preview_core_prunes_extracted_dds_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "native_preview_core"
            dds_root = cache_root / "dds"
            dds_root.mkdir(parents=True)
            old_file = dds_root / "old.dds"
            new_file = dds_root / "new.dds"
            old_file.write_bytes(b"DDS " + (b"a" * 80))
            new_file.write_bytes(b"DDS " + (b"b" * 80))
            old_time = 1000
            new_time = 2000
            old_file.touch()
            new_file.touch()
            os.utime(old_file, (old_time, old_time))
            os.utime(new_file, (new_time, new_time))

            report = prune_native_preview_core_cache(cache_root, max_bytes=120, target_bytes=90)

            self.assertEqual(1, report["removed_files"])
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())

    def test_native_preview_core_tracks_job_root_and_prunes_after_job(self) -> None:
        source = Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8")

        self.assertIn("job_root_path", source)
        self.assertIn('report.setdefault("native_preview_core_job_root", str(job_root))', source)
        self.assertIn("post_cache_prune_report = prune_native_preview_core_cache(", source)
        self.assertIn("max_bytes=dds_cache_max_bytes", source)
        self.assertIn("shutil.rmtree(job_root, ignore_errors=True)", source)

    def test_static_native_material_index_prefers_exact_sidecars(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('job.extension == ".pam" || job.extension == ".pamlod"', source)
        self.assertIn("!candidates.empty()", source)
        self.assertIn("return candidates;", source)

    def test_native_material_index_preserves_pami_roles_and_scopes_inputs(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('xml_attr_value_from_map(attrs, {"_name", "StringItemID", "Name"})', source)
        self.assertIn('xml_attr_value_from_map(attrs, {"Value", "_path"})', source)
        self.assertIn("collect_xml_tag_blocks(scope_text, \"MaterialParameterTexture\")", source)
        self.assertIn('"PrimitiveName"', source)
        self.assertIn("relevant_bindings_for_mesh", source)
        self.assertIn("material_identity_requires_exact_path_match", source)
        self.assertIn("scoped_materials.size() <= 1", source)
        self.assertIn("native material inputs scoped to this batch", source)
        self.assertIn('p.find("colorblendingmask")', source)
        self.assertIn('material_output_quality = "exact"', source)

    def test_native_material_index_trusts_exact_wrapper_order_for_single_and_unknown_batches(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("parsed_sidecar->material_wrapper_count > 0", source)
        self.assertIn("parsed_sidecar->material_wrapper_count == sidecar_scoped_mesh_count", source)
        self.assertIn("texture_ref.material_wrapper_index < sidecar_scoped_mesh_count", source)
        self.assertIn("matched_mesh = true;", source)
        self.assertIn("rejected cross-wrapper candidate", source)
        self.assertIn('desired_role == "normal"', source)
        self.assertIn('parameter_key.find("normaltexture")', source)

    def test_native_material_index_reads_technique_parameter_declarations(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("struct TechniqueParameterInfo", source)
        self.assertIn("cached_technique_index", source)
        self.assertIn("cached_package_technique_index", source)
        self.assertIn("package_root_pamt_paths", source)
        self.assertIn("technique_parameter_for_name", source)
        self.assertIn("srgb_mode_for_role", source)
        self.assertIn("srgb_mode", source)
        self.assertIn("parameter_declared_by", source)
        self.assertIn("native technique index: files=", source)

    def test_native_material_index_keeps_uint_alpha_test_flags(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('{"MaterialParameterUint", "uint"}', source)
        self.assertIn("material_parameters_enable_flag", source)
        self.assertIn("binding.alpha_test_enabled = material_parameters_enable_flag", source)
        self.assertIn('"AlphaTest"', source)
        self.assertIn('"\\"alpha_test_enabled\\":"', source)
        self.assertIn("binding_ptr->alpha_test_enabled", source)
        self.assertIn('rule.find("alphaclip")', source)
        self.assertIn('rule.find("cutout")', source)

    def test_native_material_layers_preserve_explicit_texture_channel_suffixes(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        channel_block = source[
            source.index("static std::string layer_channel_from_parameter"):
            source.index("static int layer_channel_index", source.index("static std::string layer_channel_from_parameter"))
        ]

        self.assertLess(channel_block.index('key.ends_with("g")'), channel_block.index('key.find("grime")'))
        self.assertIn('key.ends_with("b")', channel_block)
        self.assertIn('key.ends_with("a")', channel_block)
        self.assertIn(
            'layer.layer_channel = base != nullptr && !base->layer_channel.empty() ? base->layer_channel : "r";',
            source,
        )

    def test_d3d11_preview_does_not_overpaint_duplicate_base_material_layer(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("return std::clamp(layer.weight, 0.0f, 1.0f);", source)
        self.assertIn("float tint_alpha = saturate(layer_tint[ID].a);", source)
        self.assertIn("float layer_lifted_luma = saturate", source)
        self.assertIn("float3 layer_colorized = saturate", source)
        self.assertIn("float layer_colorize_strength = saturate", source)
        self.assertIn('const bool draw_albedo_layer = lower_copy(layer.role) != "base";', source)
        self.assertIn("(draw_albedo_layer && layer.diffuse_srv) ? 1.0f : 0.0f", source)
        self.assertNotIn("0.68 : layer_tint", source)

    def test_native_core_keeps_weapon_masked_layer_tint_off_base(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        layer_start = source.index("static std::vector<MaterialLayer> compile_material_layers")
        layer_end = source.index("static std::string material_layer_json", layer_start)
        layer_source = source[layer_start:layer_end]
        tint_start = source.index("static bool weapon_metal_base_tint_should_stay_masked")
        tint_end = source.index("static bool mesh_prefers_sidecar_dye_tint", tint_start)
        tint_source = source[tint_start:tint_end]

        self.assertIn("mesh_local_surface_has_strong_nonmetal_token", source)
        self.assertIn("weapon_layer_stack", layer_source)
        self.assertIn("binding_is_layer_diffuse(*binding, base, weapon_layer_stack && selected_base_layer)", layer_source)
        self.assertIn("selected_base_layer ? 0.48f", layer_source)
        self.assertIn("layer.tint[3] = detail_layer ? 0.68f : 0.55f;", layer_source)
        self.assertIn("std::stable_sort(overlays.begin(), overlays.end()", layer_source)
        self.assertIn('role.find("detail") != std::string::npos', layer_source)
        self.assertIn("weapon_metal_base_tint_should_stay_masked(base, mesh)", source)
        self.assertIn('channel == "g"', tint_source)
        self.assertIn('parameter.find("diffusetextureg")', tint_source)

    def test_native_preview_core_treats_eye_cover_as_alpha_eye_surface(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("kNativeMaterialSemanticsVersion = 6", source)
        self.assertIn("evidence_contains_eye_surface_token", source)
        self.assertIn("evidence_contains_eye_cutout_surface_token", source)
        self.assertIn('lower.find("eyecover")', source)
        self.assertIn('lower.find("eyelid")', source)
        self.assertIn("batch_is_eye_surface", source)
        self.assertIn("batch_uses_alpha_cutout", source)
        self.assertIn("batch_alpha_threshold", source)
        self.assertIn('batch_is_eye_surface ? 0.05f', source)
        self.assertIn('"\\"alpha_mode\\":\\"" << (batch_uses_alpha_cutout ? "alpha_cutout" : "opaque")', source)
        self.assertIn('"\\"two_sided\\":" << ((batch_is_hair || batch_is_eye_surface) ? "true" : "false")', source)
        self.assertIn("glossy_nonmetal:eye_surface_token", source)

    def test_native_material_index_blocks_unsafe_direct_sibling_variants(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("direct_sibling_sidecar_variant_allowed_for_fuzzy_match", source)
        self.assertIn('const std::string prefix = model_stem_lower + "_"', source)
        self.assertIn('suffix == "in"', source)
        self.assertIn("direct_sibling_sidecar_variant_allowed_for_fuzzy_match(model_stem_lower, ref_stem)", source)

    def test_native_preview_core_reports_material_quality_gate(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        python_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("material_quality_safe", source)
        self.assertIn("base_low_res_count", source)
        self.assertIn("base_low_confidence_count", source)
        self.assertIn("base_technical_count", source)
        self.assertIn("native_base_quality", source)
        self.assertIn("selected_texture_examples", source)
        self.assertIn("job_allows_texture_role", source)
        self.assertIn("visible_texture_mode", source)
        self.assertIn("best_base_binding_for_mode", source)
        self.assertIn("visible_class_for_binding", source)
        self.assertIn("technical_for_visible_base", source)
        self.assertIn("native_asset_family_json", source)
        self.assertIn("asset_family_reference_count", source)
        self.assertIn("kNativePackageSchemaVersion", source)
        self.assertIn("kNativeMaterialGraphVersion", source)
        self.assertIn("NativeMaterialGraph", source)
        self.assertIn("native material graph: version=", source)
        self.assertIn("material_semantics_version", source)
        self.assertIn("material_graph_version", source)
        self.assertIn("material_slots_json", source)
        self.assertIn("selection_decisions_json", source)
        self.assertIn('\\"dds_upload_policy\\"', source)
        self.assertIn("dds_format_is_data_only_for_visible_base", source)
        self.assertIn("collect_xml_tag_blocks", source)
        self.assertIn("add_layer_family_sibling_refs", source)
        self.assertIn("cached_parsed_material_sidecar", source)
        self.assertIn("sidecar_parse_cache_job_hits", source)
        self.assertIn("extract_material_parameters", source)
        self.assertIn("compile_material_layers", source)
        self.assertIn("material_layers", source)
        self.assertIn("primary_material_layer", source)
        self.assertIn("layer_role", source)
        self.assertIn("evidence_grade", source)
        self.assertIn("reconstruct_partial_dds", source)
        self.assertIn("cached_pathc_collection_native", source)
        self.assertIn("calculate_pa_checksum", source)
        self.assertIn("kNativeDdsExtractionVersion", source)
        self.assertIn("native_dds_v", source)
        self.assertIn("parameter_is_authoritative_visible_base", source)
        self.assertIn("base_authoritative_small_slot", source)
        self.assertIn("_native_preview_core_manifest_metadata", python_source)
        self.assertIn("Native Asset Family: schema=v", python_source)
        self.assertIn("D3D11 runtime is native-only", python_source)
        self.assertIn("_native_preview_core_failure_result", python_source)
        self.assertNotIn("_native_preview_core_reference_metadata", python_source)
        self.assertNotIn("compatibility fallback used", python_source)
        self.assertNotIn("requires Python material resolver", python_source)
        self.assertNotIn("_native_preview_core_quality_fallback_reason", python_source)
        self.assertNotIn("Native Preview Core: material quality fallback", python_source)
        self.assertIn("D3D11 package source: native-core", python_source)

    def test_native_base_selection_prefers_visible_layer_over_low_authority_overlay(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        selector_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        selector_end = source.index("static std::string shader_rule_for_family", selector_start)
        selector = source[selector_start:selector_end]
        visible_start = source.index("static std::string visible_class_for_binding")
        visible_end = source.index("static bool visible_class_allowed_for_mode", visible_start)
        visible = source[visible_start:visible_end]

        self.assertIn('hint.find("overlaycolor")', visible)
        self.assertIn("low_authority_base_path(raw_path)", visible)
        self.assertIn('return "visible_generic";', visible)
        self.assertIn('visible_class == "layer_visible"', source)
        self.assertIn("has_non_low_authority_visible_base", selector)
        self.assertIn("has_authoritative_sidecar_base_for_mesh", selector)
        self.assertIn("authoritative_visible_base", selector)
        self.assertIn("authoritative_wrapper_visible_base_for_mesh", source)
        self.assertIn("placeholder_visible_base_path", source)
        authoritative_start = source.index("static bool authoritative_wrapper_visible_base_for_mesh")
        authoritative_end = source.index("static bool support_role_requires_material_scope", authoritative_start)
        authoritative = source[authoritative_start:authoritative_end]
        self.assertNotIn("largest_dimension < 512", authoritative)
        self.assertIn("base_binding_is_low_authority_overlay", source)
        self.assertIn("best_visible_layer_base_fallback", source)
        self.assertIn("visible_layer_albedo_used", source)
        self.assertIn("base_low_authority_overlay", source)
        self.assertIn("if (base_binding_is_low_authority_overlay(&binding)) return false;", authoritative)
        self.assertIn("if (", selector)
        self.assertIn("low_authority", selector)
        self.assertIn("has_non_low_authority_visible_base", selector)
        self.assertIn("!(authoritative_visible_base && identity_score >= 120)", selector)
        self.assertIn("(has_non_low_authority_visible_base || has_authoritative_sidecar_base_for_mesh)", selector)
        self.assertIn('parameter_key.find("detaildiffuse")', selector)
        self.assertIn("score += 260", selector)
        self.assertNotIn("score -= authoritative_wrapper_visible_base_for_mesh(binding, mesh) ? 36 : 220", selector)
        self.assertIn('binding.visible_class != "visible_generic"', selector)
        self.assertIn("material_identity_text_match_score", source)
        self.assertIn('"hel", "helmet", "mask"', source)
        self.assertIn('"cloak", "flag", "cloth", "fabric"', source)
        self.assertIn("submesh_specific_match", source)
        self.assertIn("return 220 + std::min(std::max(text_score, 0), 180)", source)
        self.assertIn("!base_low_authority", source)
        self.assertIn("lookup_relevant", source)
        self.assertIn("if (!result.empty() || job.package_root.empty()) return result;", source)
        self.assertNotIn("by_path", source)

    def test_native_base_selection_rejects_cross_part_texture_family_before_scoring(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        base_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        base_end = source.index("static std::string shader_rule_for_family", base_start)
        base_selector = source[base_start:base_end]
        fallback_start = source.index("static const TextureBinding* best_visible_layer_base_fallback")
        fallback_end = source.index("static bool evidence_token_boundary", fallback_start)
        fallback_selector = source[fallback_start:fallback_end]

        self.assertIn("base_binding_has_unsafe_cross_part_texture_family", source)
        self.assertIn("texture_family_clearly_matches_mesh", source)
        self.assertIn('append_rejected_binding_example(rejected_examples, "base", "cross-part"', base_selector)
        self.assertIn('append_rejected_binding_example(rejected_examples, "base", "cross-part"', fallback_selector)
        self.assertLess(
            base_selector.index("base_binding_has_unsafe_cross_part_texture_family(binding, mesh)"),
            base_selector.index('int score = material_match_score(binding, mesh, "base")'),
        )
        self.assertLess(
            fallback_selector.index("base_binding_has_unsafe_cross_part_texture_family(binding, mesh)"),
            fallback_selector.index('int score = material_match_score(binding, mesh, "base")'),
        )
        self.assertIn("&package.rejected_texture_examples", source)

    def test_native_base_selection_rejects_wrong_family_layer_albedo_before_skin_base(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        base_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        base_end = source.index("static std::string shader_rule_for_family", base_start)
        base_selector = source[base_start:base_end]
        fallback_start = source.index("static const TextureBinding* best_visible_layer_base_fallback")
        fallback_end = source.index("static bool evidence_token_boundary", fallback_start)
        fallback_selector = source[fallback_start:fallback_end]

        self.assertIn("parameter_is_generic_color_texture_layer", source)
        self.assertIn("base_binding_is_layer_albedo_candidate", source)
        self.assertIn("base_binding_is_wrong_family_layer_or_environment", source)
        self.assertIn("base_binding_texture_family_matches_mesh", source)
        self.assertIn("selected_base_is_semantically_unsafe_skin_albedo", source)
        self.assertIn("has_mesh_family_visible_base", base_selector)
        self.assertIn("wrong_family_layer_base && has_mesh_family_visible_base", base_selector)
        self.assertIn('append_rejected_binding_example(rejected_examples, "base", "wrong-family-layer"', base_selector)
        self.assertIn("has_mesh_family_layer_base", fallback_selector)
        self.assertIn("wrong_family_layer_base && has_mesh_family_layer_base", fallback_selector)
        self.assertIn('path_text.find("texturelayer")', source)
        for token in ('"scar"', '"soil"', '"floor"', '"ground"', '"terrain"', '"akapen"'):
            self.assertIn(token, source)
        self.assertIn("base_wrong_family_layer", source)
        self.assertIn("wrong_family_layer", source)
        self.assertIn("wrong-family layer/terrain base fallback", source)
        self.assertLess(
            base_selector.index("wrong_family_layer_base && has_mesh_family_visible_base"),
            base_selector.index('int score = material_match_score(binding, mesh, "base")'),
        )
        self.assertLess(
            fallback_selector.index("wrong_family_layer_base && has_mesh_family_layer_base"),
            fallback_selector.index('int score = material_match_score(binding, mesh, "base")'),
        )

    def test_native_base_selection_rejects_chain_base_for_non_chain_parts(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        refs_start = source.index("const std::vector<SidecarTextureRef>& refs")
        refs_end = source.index("std::string pre_shader_family", refs_start)
        refs_source = source[refs_start:refs_end]

        self.assertIn('"chain"', source)
        self.assertIn("model_family_fallback_allowed_for_sidecar_ref", source)
        self.assertIn("material_identity_has_conflicting_specific_part(ref_material_key, model_family_key, \"\")", source)
        self.assertIn("material_identity_has_conflicting_specific_part(texture_family_key, model_family_key, \"\")", source)
        self.assertIn(
            "model_family_fallback_allowed_for_sidecar_ref(ref_material_key, texture_family_key, model_family_key)",
            refs_source,
        )
        self.assertNotIn("!matched_mesh && material_keys_overlap(ref_material_key, model_family_key)", refs_source)

    def test_native_shader_family_does_not_parse_pbd_material_as_shader(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        shader_start = source.index("static std::string extract_shader_family_hint")
        shader_end = source.index("static std::string xml_attr_value", shader_start)
        shader_source = source[shader_start:shader_end]
        category_start = source.index("static std::string material_category_for_bindings")
        category_end = source.index("static float material_category_confidence", category_start)
        category_source = source[category_start:category_end]

        self.assertIn(r"(?:^|[\\s<])(?:_materialName|MaterialName|TechniqueName)", shader_source)
        self.assertIn("metal_evidence", category_source)
        self.assertIn("local_evidence", category_source)
        self.assertIn("local_metal_evidence", category_source)
        self.assertIn("weak_equipment_metal_evidence", category_source)
        self.assertIn('evidence_contains_token(evidence, "helmet")', category_source)
        self.assertIn('evidence_contains_token(evidence, "helm")', category_source)
        self.assertNotIn('evidence_contains_token(evidence, "hel")', category_source)
        self.assertLess(category_source.index("if (metal_evidence)"), category_source.index("if (cloth_evidence)"))

    def test_native_base_selection_trusts_authoritative_wrapper_for_unknown_mesh_names(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        unsafe_start = source.index("static bool base_binding_has_unsafe_cross_part_texture_family")
        unsafe_end = source.index("static void append_rejected_binding_example", unsafe_start)
        unsafe_selector = source[unsafe_start:unsafe_end]
        base_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        base_end = source.index("static std::string shader_rule_for_family", base_start)
        base_selector = source[base_start:base_end]
        fallback_start = source.index("static const TextureBinding* best_visible_layer_base_fallback")
        fallback_end = source.index("static bool evidence_token_boundary", fallback_start)
        fallback_selector = source[fallback_start:fallback_end]

        self.assertIn("if (material_wrapper_matches_mesh_local_index(binding, mesh)) return false;", unsafe_selector)
        self.assertLess(
            unsafe_selector.index("material_wrapper_matches_mesh_local_index(binding, mesh)"),
            unsafe_selector.index("material_identity_has_conflicting_specific_part"),
        )
        self.assertIn("binding.material_wrapper_index != mesh.source_local_submesh_index", base_selector)
        self.assertIn("binding.material_wrapper_index != mesh.source_local_submesh_index", fallback_selector)
        self.assertIn("base_binding_has_unsafe_cross_part_texture_family(binding, mesh)", base_selector)
        self.assertIn("base_binding_has_unsafe_cross_part_texture_family(binding, mesh)", fallback_selector)

    def test_native_layer_stack_does_not_treat_skinned_standard_as_skin(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        hold_start = source.index("static bool shader_rule_holds_layer_albedo")
        hold_end = source.index("static bool shader_rule_supports_conservative_layer_stack", hold_start)
        hold = source[hold_start:hold_end]
        compile_start = source.index("static std::vector<MaterialLayer> compile_material_layers")
        compile_end = source.index("static std::string material_layer_json", compile_start)
        compiler = source[compile_start:compile_end]

        self.assertIn('shader_family.find("skinnedmeshskin")', hold)
        self.assertIn('shader_family.find("skinnedmeshhair")', hold)
        self.assertNotIn('rule.find("skin")', hold)
        self.assertIn("shader_rule_supports_conservative_layer_stack", source)
        self.assertIn('rule.find("standard")', source)
        self.assertIn('rule.find("cloth")', source)
        self.assertIn('mode == "mesh_base_first" && !shader_rule_supports_conservative_layer_stack', compiler)
        self.assertIn("seen_layer_keys", compiler)
        self.assertIn('role == "overlay") return false', source)
        self.assertIn("placeholder_layer_mask_path", source)
        self.assertIn("placeholder_visible_base_path(binding.archive_path)", source)
        self.assertIn("placeholder_layer_mask_path(mask->archive_path)", compiler)
        self.assertIn("keep_layer_stack_aux", source)
        self.assertIn('parameter_key.find("heighttexture")', source)

    def test_native_core_emits_tool_side_pbd_cloth_payloads(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("pbd_xml_sidecar", source)
        self.assertIn("_pbdSimulationMaterialName", source)
        self.assertIn("extract_native_pbd_sidecar_hints", source)
        self.assertIn("parse_native_pbd_config_materials", source)
        self.assertIn("resolve_native_pbd_material_settings", source)
        self.assertIn("build_native_cloth_runtime_batch", source)
        self.assertIn("build_native_cloth_constraints", source)
        self.assertIn("build_native_cloth_pin_weights", source)
        self.assertIn("binding.pbd_simulation_material_name = pbd_hint->simulation_material_name", source)
        self.assertIn('return "spline";', source)
        self.assertIn("native_pbd_hint_is_soft_physics", source)
        self.assertIn("native_pbd_runtime_should_use_attachment_anchors", source)
        self.assertIn("collect_native_attachment_anchor_positions", source)
        self.assertIn("attachment_anchors.empty() ? nullptr : &attachment_anchors", source)
        self.assertIn("return best_score >= 80 ? best : nullptr;", source)
        self.assertNotIn("hints.size() == 1 && !hints.front().simulation_material_name.empty()", source)
        self.assertIn('stem + "_cloth_particles.bin"', source)
        self.assertIn('stem + "_cloth_pins.bin"', source)
        self.assertIn('stem + "_cloth_constraints.bin"', source)
        self.assertIn('\\"cloth_runtime_schema\\":1', source)
        self.assertIn('\\"cloth_particle_file\\":\\"', source)
        self.assertIn('\\"cloth_collision_enabled\\":false', source)
        self.assertIn("native tool-side PBD physics runtime", source)

    def test_native_core_allows_pbd_generic_layer_stack_for_cloaks(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        layer_start = source.index("static std::vector<MaterialLayer> compile_material_layers")
        layer_end = source.index("static std::string material_layer_json", layer_start)
        layer_source = source[layer_start:layer_end]

        self.assertIn('rule == "generic"', source)
        self.assertIn('pre_shader_rule.find("generic") != std::string::npos && native_pbd_hints_have_soft_physics(parsed_sidecar->pbd_hints)', source)
        self.assertIn('rule.find("generic") != std::string::npos', source)
        self.assertIn('!binding->pbd_simulation_material_name.empty()', source)
        self.assertIn('binding_shader_rule.find("generic") != std::string::npos && binding->pbd_simulation_material_name.empty()', layer_source)

    def test_d3d11_host_does_not_use_rich_material_inputs_as_base_override(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        parse_start = source.index("static std::vector<PreviewBatch> parse_manifest_batches")
        parse_end = source.index("static ViewSettings parse_view_settings", parse_start)
        parse_source = source[parse_start:parse_end]

        self.assertIn('batch.base_dds = dds_slot_source(object, "base");', parse_source)
        self.assertIn('const std::string descriptor = json_object_field(object, slot);', source)
        self.assertIn('if (!json_bool_field(descriptor, "available", true)) return L"";', source)
        self.assertIn('if (!json_bool_field(descriptor, "direct_upload_candidate", true)) return L"";', source)
        self.assertNotIn('best_material_dds_for_role(object, "base")', parse_source)

    def test_d3d11_host_consumes_schema_v8_material_layer_stack(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("kMaxMaterialLayers = 4", source)
        self.assertIn("parse_material_layers", source)
        self.assertIn("json_object_array_field", source)
        self.assertIn("parse_primary_material_layer", source)
        self.assertIn("return std::clamp(layer.weight, 0.0f, 1.0f);", source)
        self.assertIn("float tint_alpha = saturate(layer_tint[ID].a);", source)
        self.assertIn('const bool draw_albedo_layer = lower_copy(layer.role) != "base";', source)
        self.assertIn("material_layer_active_batches", source)
        self.assertIn('\\"material_layer_roles\\"', source)
        self.assertIn("Texture2D layer0_diffuse_tex : register(t10)", source)
        self.assertIn("Texture2D layer3_diffuse_tex : register(t13)", source)
        self.assertIn("Texture2D layer0_mask_tex : register(t14)", source)
        self.assertIn("Texture2D layer0_material_tex : register(t18)", source)
        self.assertIn("Texture2D layer0_normal_tex : register(t22)", source)
        self.assertIn("Texture2D layer0_height_tex : register(t26)", source)
        self.assertIn("constants.flags4 = DirectX::XMFLOAT4", source)
        self.assertIn("normal_y_policy", source)
        self.assertIn("invert_normal_y", source)
        self.assertIn("flags3.y", source)
        self.assertIn("constants.layer_params[layer_index] = DirectX::XMFLOAT4", source)
        self.assertIn("ID3D11ShaderResourceView* srvs[kTotalSrvCount]", source)
        self.assertIn("context_->PSSetShaderResources(0, kTotalSrvCount, srvs)", source)
        self.assertIn("CREATETEX_FORCE_SRGB", source)
        self.assertIn('compile_shader(kShaderSource, "ps_main", "ps_4_0"', source)

    def test_d3d11_mesh_edit_mode_draws_blender_style_topology_overlay(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("void draw_mesh_edit_overlay(const PreviewRenderView& view)", source)
        self.assertIn("mesh_edit_batch_editable_in_view(batch, view)", source)
        self.assertIn("constants.base_color_flip = mesh_edit_flat", source)
        self.assertIn("mesh_edit_flat ? nullptr : batch.base_srv.Get()", source)
        self.assertIn("mesh_edit_.show_vertices", source)
        self.assertIn("mesh_edit_source_vertex_selected", source)
        self.assertIn("mesh_edit_preserve_materials_for_batch(batch)", source)
        self.assertIn("const bool mesh_edit_flat = mesh_edit_active && !mesh_edit_preserve_materials_for_batch(batch)", source)
        self.assertIn("else if (!dense_topology_overlay)", source)
        self.assertIn("batch_is_reference(batch) || !batch_visible_in_view(batch, PreviewViewRole::Replacement)", source)
        self.assertIn("add_thick_line_depth(p[0], depth_z[0], p[1], depth_z[1], 2.4f, 1.0f, 0.48f, 0.12f)", source)
        self.assertIn("mesh_edit_.tool == \"remove\"", source)
        self.assertIn("add_ring(ScreenPoint{static_cast<float>(cursor_x_), static_cast<float>(cursor_y_)}, mesh_edit_.radius_pixels + 2.0f", source)
        self.assertIn("void draw_mesh_edit_vertex_dots_instanced(", source)
        self.assertIn("add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 4.5f, 1.0f, 0.52f, 0.12f)", source)
        self.assertIn("add_instance(screen_vertex.screen_x, screen_vertex.screen_y, screen_vertex.depth_z, 2.8f, 0.18f, 0.82f, 1.0f)", source)
        self.assertIn("context_->DrawInstanced(6u, static_cast<UINT>(instances.size()), 0u, 0u)", source)

    def test_native_core_scopes_sidecar_wrappers_before_dds_extraction(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("score_material_wrapper_block_for_preview", source)
        self.assertIn('collect_xml_tag_blocks(text, "SkinnedMeshMaterialWrapper")', source)
        self.assertIn("material_keys_overlap", source)
        self.assertIn("normalized_texture_family_key", source)
        self.assertIn("build_material_bindings(job, index, parsed.meshes, package)", source)
        self.assertIn("refs_considered", source)
        self.assertIn("sidecar skipped unrelated material wrapper", source)
        self.assertIn("SkinnedMesh(?:Skin(?:Wrinkle)?|Standard(?:_Ver[0-9]+)?|Cloth(?:_Ver[0-9]+)?|Hair|Fur", source)
        self.assertNotIn("best_wrapper_by_material", source)

    def test_native_core_scores_pac_layouts_and_rejects_unsafe_geometry(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("struct PacVertexLayout", source)
        self.assertIn("evaluate_native_submesh_quality", source)
        self.assertIn("pac40_uv8_n16", source)
        self.assertIn("pac40_uv32_n16", source)
        self.assertIn("alternate_vertex_layouts", source)
        self.assertIn("pac32_uv8_n16", source)
        self.assertIn("pac48_uv40_n16", source)
        self.assertIn("degenerate_triangle_ratio", source)
        self.assertIn("edge_outlier_ratio", source)
        self.assertIn("uv_edge_outlier_ratio", source)
        self.assertIn("uv_degenerate_triangle_ratio", source)
        self.assertIn("collect_candidates_for_layouts(primary_vertex_layouts)", source)
        self.assertIn("has_confident_primary", source)
        self.assertIn("filtered unsafe native PAC submesh", source)
        self.assertIn("safe_faces >= static_cast<int>(static_cast<float>(original.faces) * 0.60f)", source)
        self.assertIn("uv_finite_ratio", source)
        self.assertIn("normal_valid_ratio", source)
        self.assertIn("native geometry unsafe", source)
        self.assertIn('\\"geometry_quality\\":{', source)
        self.assertIn('\\"layout\\":\\"', source)

    def test_native_core_hair_flow_and_layer_modes_are_conservative(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        role_start = source.index("static std::string role_from_parameter_shader_and_name")
        role_end = source.index("static std::string semantic_type_for_role", role_start)
        role_source = source[role_start:role_end]
        layer_start = source.index("static std::vector<MaterialLayer> compile_material_layers")
        layer_end = source.index("static std::string material_layer_json", layer_start)
        layer_source = source[layer_start:layer_end]

        self.assertLess(role_source.index('p.find("flow")'), role_source.index('t.find("_n.dds")'))
        self.assertIn('return "flow";', role_source)
        self.assertIn('name.find("_flow")', source)
        self.assertIn('name.find("_dr.dds")', source)
        self.assertIn('p.find("ssdm")', role_source)
        self.assertIn('p.find("direction")', role_source)
        self.assertIn('path_has_suffix_stem(raw_path, "_dr")', source)
        self.assertIn('mode == "mesh_base_first" && !shader_rule_supports_conservative_layer_stack', layer_source)
        self.assertIn('if (mask == nullptr)', layer_source)
        self.assertIn("native_preview_base_tint_strength", source)
        self.assertIn("reliable_visible_base_texture", source)
        self.assertIn('if (reliable_visible_base_texture(base)) return 0.0f;', source)
        self.assertIn('\\"base_tint_strength\\":', source)
        self.assertIn('layer.weight <= 0.001f ? 0.14f : layer.weight', layer_source)
        self.assertIn('binding_shader_rule == "hair"', layer_source)
        self.assertIn('binding_shader_rule == "skin"', layer_source)
        self.assertIn('binding_shader_family.find("skinnedmeshhair")', layer_source)
        self.assertIn('binding_shader_family.find("skinnedmeshskin")', layer_source)
        self.assertIn('\\"alpha_mode', source)
        self.assertIn('\\"two_sided', source)
        self.assertIn('\\"uv_flip_policy\\":\\"legacy_no_flip', source)
        self.assertIn('\\"normal_y_policy\\":\\"shader_invert_legacy_compat', source)

    def test_d3d11_preview_has_first_class_emissive_slot(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        package_source = Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8")
        native_package_source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('"emissive"', package_source)
        self.assertIn('"emissive_intensity"', package_source)
        self.assertIn('return "emissive";', native_package_source)
        self.assertIn('role == "emissive"', native_package_source)
        self.assertIn('best_binding_for_role(bindings, mesh, "emissive"', native_package_source)
        self.assertIn('{"emissive", emissive}', native_package_source)
        self.assertIn('\\"emissive_intensity\\":', native_package_source)
        self.assertIn("Texture2D emissive_tex : register(t9)", source)
        self.assertIn("batch.emissive_dds = dds_slot_source(object, \"emissive\")", source)
        self.assertIn("batch.emissive_intensity = std::clamp(json_float_field(object, \"emissive_intensity\"", source)
        self.assertIn(
            "load_batch_texture(batch.emissive_dds, batch.emissive_png, batch.emissive_srv, \"emissive\", stats, batch.live_texture_bytes)",
            source,
        )
        self.assertIn("emissive_tex.Sample(preview_sampler, uv)", source)

    def test_d3d11_preview_uses_procedural_reflection_for_metal_materials(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        package_source = Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8")

        self.assertIn("float3 reflected_view = normalize(reflect(-v, n));", source)
        self.assertIn("preview_environment_color", source)
        self.assertIn("ggx_distribution", source)
        self.assertIn("fresnel_schlick", source)
        self.assertIn("front_softbox", source)
        self.assertIn("back_softbox", source)
        self.assertIn("opposite_softbox", source)
        self.assertIn("wrapped_ndotl", source)
        self.assertIn("env_fresnel", source)
        self.assertIn("direct_metal_response", source)
        self.assertIn("user_metalness_scale", source)
        self.assertIn("category_metal_fallback", source)
        self.assertIn("metalness = max(metalness, category_metal_fallback);", source)
        self.assertIn("roughness = min(roughness, lerp(0.34, 0.16, category_confidence));", source)
        self.assertIn("normalized_lighting_preset", source)
        self.assertIn("apply_render_tuning_preset(", source)
        self.assertIn("lower_copy(stats_.lighting_preset)", source)
        self.assertIn("float3 fill_dir", source)
        self.assertIn("float3 back_dir", source)
        self.assertIn("has_metal_preview_response", package_source)
        self.assertIn('"shiny_metal_inspection"', package_source)
        self.assertNotIn("tone_exposure = min(tone_exposure, 0.82)", package_source)
        self.assertNotIn("specular_max = max(specular_max, 0.42)", package_source)
        for token in ("gold", "silver", "copper", "bronze", "brass", "chrome"):
            self.assertIn(f'"{token}"', package_source)
        self.assertIn("_source_or_descriptor_has_weapon_surface", package_source)

    def test_native_core_emits_material_category_and_promotion_policy(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("material_category_for_bindings", source)
        self.assertIn("pbd_hint_count", source)
        self.assertIn("pbd_soft_hint_count", source)
        self.assertIn("pbd_cloth_hint_count", source)
        self.assertIn("evidence_contains_token", source)
        self.assertIn('evidence.find("skinnedmeshcloth")', source)
        self.assertIn('evidence.find("skinnedmeshskin")', source)
        category_start = source.index("static std::string material_category_for_bindings")
        category_end = source.index("static float material_category_confidence", category_start)
        category_source = source[category_start:category_end]
        self.assertLess(category_source.index('evidence.find("skinnedmeshcloth")'), category_source.index('evidence.find("skinnedmeshskin")'))
        self.assertLess(category_source.index('evidence_contains_token(evidence, "handle")'), category_source.index('evidence_contains_token(evidence, "hand")'))
        self.assertNotIn("pbd_simulation_material_name", category_source)
        self.assertIn("equipment_surface_evidence", category_source)
        self.assertIn("mesh_has_crimson_armor_equipment_surface", source)
        self.assertIn("binding_has_authoritative_model_family_material_response", source)
        self.assertIn("texture_family_key_is_specific_material_response", source)
        self.assertIn("has_authoritative_model_family_material_response(bindings, mesh)", category_source)
        self.assertIn("armor_family_material_response", category_source)
        self.assertIn("mesh_has_crimson_weapon_surface", source)
        self.assertIn("weapon_family_material_response", category_source)
        self.assertIn('"metal:armor_family_material_response"', source)
        self.assertIn('"metal:weapon_family_material_response"', source)
        self.assertIn('binding->source_authority == "exact_sidecar"', source)
        self.assertIn('binding->material_output_quality == "exact"', source)
        self.assertIn('texture_family_key.find("texturelayer")', source)
        self.assertIn("material_category_confidence", source)
        self.assertIn("promoted_global_material_response", source)
        self.assertIn("material_response_disposition", source)
        self.assertIn("material_response_promoted", source)
        self.assertIn('material_category == "metal" && promoted_global_material_response(material)', source)
        self.assertIn("has_metal_preview_response", source)
        self.assertIn("native_lighting_preset_for_job(job, has_metal_preview_response)", source)
        self.assertIn('\\"lighting_preset\\":\\"', source)
        self.assertIn('\\"material_contract_schema\\":2', source)
        self.assertIn('\\"material_channel_contract_schema\\":2', source)
        self.assertIn('\\"texture_quality_schema\\":1', source)
        self.assertIn('\\"diffuse_wrap_bias\\":', source)
        self.assertIn('\\"metalness\\":', source)
        self.assertIn('\\"native_material_hints\\":{', source)
        self.assertIn("material_category_reason_for_bindings", source)
        self.assertIn('\\"material_category_reason\\"', source)
        self.assertIn("add_support_base_sibling_ref", source)
        self.assertIn("texture_path_has_visual_support_suffix", source)
        self.assertIn('add_sidecar_texture_ref(refs, seen, diffuse_path, "_baseColorTexture"', source)
        self.assertIn('"promoted_ao_roughness_nonmetal_capped"', source)
        self.assertIn('"layer_only"', source)
        self.assertIn("base_binding_is_low_authority_overlay(base)", source)
        self.assertIn('evidence_contains_token(evidence, "blade")', source)
        self.assertNotIn('evidence_contains_token(evidence, "sword")', category_source)
        self.assertNotIn('evidence_contains_token(evidence, "knife")', category_source)
        self.assertNotIn('evidence_contains_token(evidence, "axe")', category_source)
        self.assertNotIn('evidence_contains_token(evidence, "spear")', category_source)
        self.assertIn("structural_metal_evidence", category_source)
        self.assertIn("metal_color_evidence", category_source)
        self.assertIn("scalar_metal_evidence", category_source)
        self.assertIn("glass_evidence", category_source)
        self.assertIn("gem_evidence", category_source)
        self.assertIn("stone_evidence", category_source)
        for token in ("stick", "shaft", "haft"):
            self.assertIn(f'evidence_contains_token(evidence, "{token}")', category_source)
        self.assertIn("eye_evidence", category_source)
        self.assertIn("tooth_evidence", category_source)
        self.assertIn("strong_nonmetal_evidence", category_source)
        self.assertIn("local_strong_nonmetal_evidence", category_source)
        self.assertIn("local_metal_evidence", category_source)
        self.assertIn("local_metal_evidence\n        ||", category_source)
        self.assertIn("weak_equipment_metal_evidence", category_source)
        self.assertIn("material_response_metal_hint_evidence", category_source)
        self.assertIn("binding_has_explicit_metalness_slot", source)
        self.assertIn("leather_material_evidence", category_source)
        self.assertIn("leather_part_evidence", category_source)
        self.assertIn("|| leather_material_evidence", category_source)
        self.assertIn("|| leather_part_evidence", category_source)
        for token in ("brow", "eyebrow", "lash", "eyelash"):
            self.assertIn(f'evidence_contains_token(evidence, "{token}")', category_source)
        for token in ("flag", "banner", "vest", "tassel", "fringe", "ribbon", "sash", "rope", "cape", "skirt", "dress", "mantle", "robe", "flap"):
            self.assertIn(f'evidence_contains_token(evidence, "{token}")', category_source)
        for token in ("gold", "silver", "copper", "bronze", "brass", "chrome"):
            self.assertIn(f'evidence_contains_token(evidence, "{token}")', category_source)
        self.assertIn('evidence_contains_token(evidence, "weapon")', source)
        self.assertIn("binding_is_tintable_visible_layer_base", source)
        self.assertIn("preview_sidecar_tint_for_surface", source)
        self.assertIn("mesh_prefers_sidecar_dye_tint", source)
        self.assertIn("visible_layer_albedo_tint_strength", source)
        self.assertIn("visible_layer_tint_applied", source)
        self.assertIn("visible_layer_tint_color", source)
        self.assertIn("native visible layer tint applied", source)
        self.assertIn("native sidecar tint applied", source)
        self.assertIn("layer_largest_dimension * 2 < base_largest_dimension", source)
        self.assertIn('return "wood";', source)
        self.assertIn('return "leather";', source)
        self.assertIn('return "eye";', category_source)
        self.assertIn('return "tooth";', category_source)
        self.assertIn('\\"roughness_hint\\"', source)
        self.assertIn('\\"metalness_hint\\"', source)
        self.assertIn('\\"specular_hint\\"', source)
        self.assertIn('\\"height_scale_hint\\"', source)
        self.assertIn('\\"tint_color\\"', source)
        self.assertIn('"specular_gloss_nonmetal_capped"', source)

    def test_native_core_uses_overlay_base_as_last_resort_visible_base(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("binding_is_overlay_base_fallback_candidate", source)
        self.assertIn("best_overlay_base_fallback", source)
        self.assertIn('parameter_key.find("overlaycolor")', source)
        self.assertIn("low_authority_base_path(binding.archive_path)", source)
        self.assertIn("!material_wrapper_matches_mesh_local_index(binding, mesh) && identity_score < 300", source)
        self.assertIn("best_overlay_base_fallback(bindings, mesh, &best_score)", source)
        self.assertIn('\\"runtime_backend\\":\\"native_cpp', source)
        self.assertIn('\\"package_builder\\":\\"cdmw_preview_core_cpp', source)
        self.assertIn('\\"renderer_contract\\":\\"d3d11_native_package', source)
        self.assertIn('\\"python_fallback_allowed\\":false', source)

    def test_native_material_category_keeps_nude_skin_from_broad_hair_shader(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        category_start = source.index("static std::string material_category_for_bindings")
        category_end = source.index("static float material_category_confidence", category_start)
        category_source = source[category_start:category_end]

        self.assertIn("strong_skin_evidence", category_source)
        self.assertIn("hair_shader_evidence", category_source)
        self.assertIn("actual_hair_evidence", category_source)
        self.assertIn('evidence_contains_token(evidence, "nude")', category_source)
        self.assertIn('evidence_contains_token(evidence, "hand")', category_source)
        self.assertIn('evidence_contains_token(evidence, "head")', category_source)
        self.assertIn("actual_hair_evidence || !strong_skin_evidence", category_source)
        self.assertIn("strong_skin_evidence || head_skin_evidence", category_source)
        self.assertIn("&& !hair_shader_evidence", category_source)
        self.assertIn("&& !actual_hair_evidence", category_source)
        self.assertLess(
            category_source.index("if ((hair_shader_evidence || actual_hair_evidence)"),
            category_source.index("if (strong_skin_evidence || head_skin_evidence)"),
        )
        self.assertLess(
            category_source.index("if (cloth_evidence)"),
            category_source.index("if (strong_skin_evidence || head_skin_evidence)"),
        )
        self.assertIn('evidence_contains_token(evidence, "uw")', category_source)
        self.assertIn('evidence_contains_token(evidence, "underwear")', category_source)

    def test_native_asset_family_resolves_side_specific_placement_files(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('add_basename(stem + "_l.prefab")', source)
        self.assertIn('add_basename(stem + "_r.prefab")', source)
        self.assertIn('{model_stem + "_l.prefab", {"Prefab / Metadata", "Prefab"}}', source)
        self.assertIn('{model_stem + "_r.prefab", {"Prefab / Metadata", "Prefab"}}', source)
        self.assertIn('{model_stem + "_l.sockets.xml", {"Attachment / Placement", "Socket XML"}}', source)
        self.assertIn('{model_stem + "_r.sockets.xml", {"Attachment / Placement", "Socket XML"}}', source)

    def test_d3d11_preview_caps_nonmetal_material_response_by_category(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("material_category_code", source)
        self.assertIn("material_category_confidence", source)
        self.assertIn("material_response_promoted", source)
        self.assertIn("flags5", source)
        self.assertIn("category_leather", source)
        self.assertIn("category_wood", source)
        self.assertIn("category_glass", source)
        self.assertIn("category_gem", source)
        self.assertIn("category_stone", source)
        self.assertIn("category_eye", source)
        self.assertIn("category_tooth", source)
        self.assertIn("known_nonmetal", source)
        self.assertIn("conservative_nonmetal", source)
        self.assertIn("category_metal_cap", source)
        self.assertIn("category_env_scale", source)
        self.assertIn("lerp(0.12, 0.32, category_confidence)", source)
        self.assertIn("bool material_response_promoted = false;", source)
        self.assertIn('json_bool_field(object, "material_response_promoted", false)', source)
        self.assertIn("promoted_material_response = flags5.z > 0.5", source)
        self.assertIn("batch.material_response_promoted ? 1.0f : 0.0f", source)
        self.assertIn("render_tuning3.w * category_env_scale", source)

    def test_d3d11_preview_shader_uses_registry_pbr_lighting_helpers(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("float ggx_distribution", source)
        self.assertIn("float geometry_smith", source)
        self.assertIn("float3 fresnel_schlick", source)
        self.assertIn("float3 aces_tonemap", source)
        self.assertIn("float3 specular_brdf = (d * g * f)", source)
        self.assertIn("albedo = saturate(base_sample.rgb);", source)
        self.assertIn("lifted_luma", source)
        self.assertIn("float3 colorized", source)
        self.assertNotIn("albedo = srgb_to_linear(base_sample.rgb);", source)
        self.assertIn("float3 mapped = aces_tonemap(color * tone_exposure);", source)
        self.assertIn("mapped = saturate((mapped - 0.5) * tone_contrast + 0.5);", source)
        self.assertIn("mapped = pow(mapped, float3(tone_gamma, tone_gamma, tone_gamma));", source)
        self.assertIn("return float4(linear_to_srgb(mapped), 1.0);", source)

    def test_native_core_material_wrappers_are_slot_authoritative_when_order_matches(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("int material_wrapper_index = -1", source)
        self.assertIn("int material_wrapper_count = 0", source)
        self.assertIn("material_wrapper_order_authoritative", source)
        self.assertIn("int sidecar_scoped_mesh_count = 0", source)
        self.assertIn("parsed_sidecar->material_wrapper_count == sidecar_scoped_mesh_count", source)
        self.assertIn("material_sidecar_matches_mesh_source", source)
        self.assertIn("binding.material_wrapper_index == mesh.source_local_submesh_index", source)
        self.assertIn("material_wrapper_matches_mesh_local_index", source)
        self.assertIn("!authoritative_wrapper_match && material_identity_has_conflicting_specific_part", source)
        self.assertIn("if (authoritative_wrapper_match) score += 210;", source)
        self.assertIn("binding.material_wrapper_order_authoritative && identity_score < 120", source)
        self.assertIn("submesh_specific_match && text_score >= 120", source)
        self.assertIn("extract_texture_refs_from_scope(block, material_name, shader_family, wrapper_index++", source)

    def test_native_material_identity_allows_variant_token_bridge_before_rejecting(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        start = source.index("static int material_identity_text_match_score")
        end = source.index("static int material_identity_match_score", start)
        identity_source = source[start:end]

        self.assertIn("token_bridge_score", identity_source)
        self.assertIn("material_key_token_cover_score(binding_key, mesh_key_a)", identity_source)
        self.assertIn("material_key_token_cover_score(texture_family_key, mesh_key_b)", identity_source)
        self.assertIn("if (token_bridge_score < 100) return 0;", identity_source)
        self.assertIn("score += token_bridge_score;", identity_source)

    def test_native_material_identity_rejects_cross_part_support_slots(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        selector_start = source.index("static const TextureBinding* best_binding_for_role")
        selector_end = source.index("static const TextureBinding* best_base_binding_for_mode", selector_start)
        support_selector = source[selector_start:selector_end]
        base_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        base_end = source.index("static std::string shader_rule_for_family", base_start)
        base_selector = source[base_start:base_end]

        self.assertIn("material_identity_specific_part_tokens", source)
        self.assertIn('"hand", "head", "foot"', source)
        self.assertIn('"uw", "underwear", "nude"', source)
        self.assertIn('"blade", "guard", "handle", "acc"', source)
        self.assertIn("material_identity_has_conflicting_specific_part", source)
        self.assertIn("conflicting_specific_part", support_selector)
        self.assertIn("rejected cross-part candidate", support_selector)
        self.assertIn("rejected cross-component candidate", support_selector)
        self.assertIn("material_binding_matches_mesh_source", source)
        self.assertNotIn("!embedded && material_identity_has_conflicting_specific_part", base_selector)
        self.assertIn("material_identity_has_conflicting_specific_part", base_selector)

    def test_native_core_expands_same_stem_prefab_components_for_item_previews(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("extract_prefab_model_paths", source)
        self.assertIn("prefab_candidate_basenames_for_model_stem", source)
        self.assertIn("prefab_model_component_refs_for_job", source)
        self.assertIn('stem + "_s.prefab"', source)
        self.assertIn('stem + "_v"', source)
        self.assertIn("prefab_component_match_stem", source)
        self.assertIn("prefab_model_path_matches_job", source)
        self.assertIn('"_op_s", "_op_v", "_v", "_s"', source)
        self.assertIn("_sub[0-9]+", source)
        self.assertIn("body|head|hair|chain|cloth|acc|belt", source)
        self.assertIn("compound_part_pattern", source)
        self.assertIn("resolve_archive_path_across_package", source)
        self.assertIn('ref.extension == ".pac"', source)
        self.assertIn('"Prefab / Components"', source)
        self.assertIn('"Model Component"', source)
        self.assertIn("native prefab composite: added", source)
        self.assertIn('parsed.parser += "+prefab_composite"', source)
        self.assertIn('component_stem + ".pac_xml"', source)
        self.assertIn("mesh.source_model_path = component.path", source)
        self.assertIn("mesh.source_component_label", source)
        self.assertIn("mesh.source_prefab_component = true", source)
        self.assertIn("const std::string mesh_source_path = mesh.source_model_path.empty() ? job.path : mesh.source_model_path", source)
        self.assertIn("binding.linked_mesh_path = mesh_source_path", source)
        self.assertIn("prefab_component", source)
        self.assertIn("source_component_label", source)
        self.assertIn("source_model_path", source)

    def test_native_core_mesh_base_first_keeps_exact_embedded_base_over_layers(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        start = source.index("static const TextureBinding* best_base_binding_for_mode")
        end = source.index("static std::string shader_rule_for_family", start)
        selection_source = source[start:end]

        self.assertIn("parameter_is_authoritative_visible_base(binding.parameter_name)", selection_source)
        self.assertIn("identity_score >= 120", selection_source)
        self.assertIn('binding.source_authority == "embedded_mesh"', selection_source)
        self.assertIn("allow_authoritative_mesh_base", selection_source)
        self.assertIn("has_authoritative_sidecar_base_for_mesh", selection_source)
        self.assertIn("authoritative_visible_base", selection_source)
        self.assertIn("authoritative_visible_base && identity_score >= 120", selection_source)
        self.assertIn("!(authoritative_visible_base && identity_score >= 120)", selection_source)
        self.assertIn('hint.find("grime")', source)
        self.assertIn('hint.find("detail")', source)
        self.assertIn("material_identity_extra_part_penalty", source)
        self.assertIn("material_key_token_cover_score", source)
        self.assertIn("material_keys_match_for_identity", source)
        self.assertIn("stable_visible_base", selection_source)
        self.assertIn("identity_score <= 0", selection_source)
        self.assertIn("score += identity_score / 2", source)
        self.assertIn("score += 180", source)
        self.assertIn('layer_role == "damage"', source)
        self.assertIn("score -= 190", source)
        self.assertIn('"hand", "head", "foot", "eye"', source)

    def test_native_core_diffuse_damage_and_opacity_do_not_become_support_albedo(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        role_start = source.index("static std::string role_from_parameter_shader_and_name")
        role_end = source.index("static std::string semantic_type_for_role", role_start)
        role_source = source[role_start:role_end]

        self.assertLess(role_source.index('p.find("diffuse")'), role_source.index('p.find("blending")'))
        self.assertIn('return "opacity";', role_source)
        self.assertIn('role == "opacity"', source)
        self.assertIn('t.find("_f.dds")', role_source)
        self.assertIn('t.find("_dr.dds")', role_source)
        self.assertIn('dds_format_is_data_only_for_visible_base(binding.dds_format)', source)
        self.assertIn("base_binding_is_layer_albedo_candidate(binding)", source)


if __name__ == "__main__":
    unittest.main()
