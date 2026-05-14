from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings
from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_core import (
    NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES,
    NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS,
    NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES,
    NativePreviewCoreServiceClient,
    build_native_preview_core_job,
    run_native_preview_core_preview_job,
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
    def test_build_job_carries_archive_entry_and_schema_v4(self) -> None:
        job = build_native_preview_core_job(
            _entry(),
            cache_root=Path("C:/cache/native"),
            output_root=Path("C:/cache/package"),
            render_settings=ModelPreviewRenderSettings(),
            package_root=Path("C:/game"),
        )

        self.assertEqual(4, job["schema_version"])
        self.assertEqual("d3d11", job["renderer_backend"])
        self.assertEqual("character/model/example/cd_example.pac", job["entry"]["path"])
        self.assertEqual("C:\\game\\0009\\1.paz", job["entry"]["paz_file"])
        self.assertTrue(job["capabilities"]["direct_dds"])
        self.assertTrue(job["capabilities"]["python_fallback_allowed"])

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

    def test_native_preview_core_is_bundled_and_archive_worker_attempts_it(self) -> None:
        spec_text = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        build_text = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        main_window_text = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        source_text = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("cdmw-preview-core.exe", spec_text)
        self.assertIn("native\\cdmw_preview_core", build_text)
        self.assertIn("run_native_preview_core_preview_job", main_window_text)
        self.assertIn("native_preview_core_enabled", main_window_text)
        self.assertIn("preview-job", source_text)
        self.assertIn("--service", source_text)
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
        self.assertIn("material_output_quality", source_text)
        self.assertIn("decoded_cache_job_hits", source_text)
        self.assertIn("prune_decoded_entry_cache", source_text)
        self.assertIn("kDecodedEntryCacheMaxEntries = 256", source_text)
        self.assertIn("kDecodedEntryCacheMaxBytes = 128ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheMaxSingleBytes = 32ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheRecycleBytes = 96ull * 1024ull * 1024ull", source_text)
        self.assertIn("kServiceMaxJobs = 8", source_text)
        self.assertIn("kServicePrivateRecycleBytes = 384ull * 1024ull * 1024ull", source_text)
        self.assertIn("process_private_bytes", source_text)
        self.assertIn("service_recycle_reason", source_text)
        self.assertIn("_get_native_preview_core_service", Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8"))

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
        self.assertIn("archive_native_prefetch_timer", source)
        self.assertIn("def _archive_native_prefetch_candidate_entries", source)
        self.assertIn("def _start_archive_native_preview_prefetch", source)
        self.assertIn("def _stop_archive_native_preview_prefetch", source)
        self.assertIn("archive_native_prefetch_thread", source)
        self.assertIn("timeout_seconds=5.0", source)
        self.assertIn("run_native_preview_core_preview_job", source)

    def test_static_native_material_index_prefers_exact_sidecars(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('job.extension == ".pam" || job.extension == ".pamlod"', source)
        self.assertIn("!candidates.empty()", source)
        self.assertIn("return candidates;", source)

    def test_native_material_index_preserves_pami_roles_and_scopes_inputs(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('xml_attr_value(tag, {"_name", "StringItemID", "Name"})', source)
        self.assertIn('xml_attr_value(tag, {"Value", "_path"})', source)
        self.assertIn('"PrimitiveName"', source)
        self.assertIn("relevant_bindings_for_mesh", source)
        self.assertIn("material_identity_requires_exact_path_match", source)
        self.assertIn("scoped_materials.size() <= 1", source)
        self.assertIn("native material inputs scoped to this batch", source)
        self.assertIn('p.find("colorblendingmask")', source)
        self.assertIn('material_output_quality = "exact"', source)

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


if __name__ == "__main__":
    unittest.main()
