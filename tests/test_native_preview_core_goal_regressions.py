from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.models import ArchiveEntry
from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
from tests.native_source_text import preview_core_source


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


class NativePreviewCoreGoalRegressionTests(unittest.TestCase):
    def test_native_preview_core_persists_source_stamped_pamt_index(self) -> None:
        source = preview_core_source()

        self.assertIn("CDMWPIDX", source)
        self.assertIn("load_pamt_index_cache", source)
        self.assertIn("write_pamt_index_cache", source)
        self.assertIn("pamt_index_source_stamp", source)
        self.assertIn("cached_pamt_index(job.entry.pamt_path, job.cache_root)", source)
        self.assertIn("native_pamt_index_cache_hit", source)
        self.assertIn("MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH", source)

    def test_native_preview_core_bounds_resident_pamt_indexes_before_memory_report(self) -> None:
        """A finished job must bound the resident PAMT set by recency and bytes.

        Keeping only the most recently touched index evicted the primary index
        whenever a job ended on a cross-package lookup, so every job reloaded
        it at ~100 ms even from the on-disk cache. Keeping everything instead
        measured ~690 MB against real archives and tripped the 512 MB
        private-bytes recycle guard, recycling the service after every job.
        The byte-budgeted recency trim is what keeps repeat previews fast
        without recycle churn; the error path still clears the cache outright.
        """

        cache_source = Path("native/cdmw_preview_core/src/owners/pamt_index_cache.cpp").read_text(encoding="utf-8")
        report_source = Path("native/cdmw_preview_core/src/owners/preview_report.cpp").read_text(encoding="utf-8")

        self.assertIn("resident_pamt_index_cache().swap(empty)", cache_source)
        self.assertIn("auto& cache = resident_pamt_index_cache()", cache_source)
        self.assertIn("static void trim_resident_pamt_indexes()", cache_source)
        # Eviction has to be least-recently-used and byte-budgeted, and every
        # cache hit has to refresh its key's recency.
        self.assertIn("resident_pamt_index_recency()", cache_source)
        self.assertIn("approximate_pamt_index_resident_bytes", cache_source)
        self.assertIn("kResidentPamtIndexMaxBytes", cache_source)
        self.assertIn("resident_pamt_index_recency()[key] = next_resident_pamt_index_tick();", cache_source)
        trim_position = report_source.index("trim_resident_pamt_indexes();")
        memory_position = report_source.index("cdmw_native_diag::current_process_memory()")
        self.assertLess(trim_position, memory_position)
        self.assertIn("native_pamt_index_resident_before_release", report_source)
        self.assertIn("native_pamt_index_resident_after_release", report_source)
        self.assertIn("native_pamt_index_cache_released", report_source)
        self.assertIn("native_pamt_index_cache_bounded", report_source)
        self.assertIn("stats.pamt_after <= kResidentPamtIndexMaxCount", report_source)
        catch_body = report_source[report_source.index("int run_preview_job(") :]
        self.assertIn("catch (const std::exception& exc) {\n        release_resident_pamt_indexes();", catch_body)

    def test_native_preview_core_bounds_cross_job_metadata_caches(self) -> None:
        """A healthy job bounds the metadata caches; the error path releases.

        Rebuilding the technique index decodes every .technique/.material entry
        of a .pamt, and repeating the cross-package basename scans reloads up
        to 64 indexes; together that cost about a second per warm job when the
        caches were released on completion. Completion now trims to bounds and
        keeps the caches resident; a failed job still clears everything.
        """

        archive_source = Path("native/cdmw_preview_core/src/owners/archive_decode.cpp").read_text(encoding="utf-8")
        graph_source = Path("native/cdmw_preview_core/src/owners/material_graph.cpp").read_text(encoding="utf-8")
        sidecar_source = Path("native/cdmw_preview_core/src/owners/material_selection.cpp").read_text(encoding="utf-8")
        lookup_source = Path("native/cdmw_preview_core/src/owners/material_archive_lookup.cpp").read_text(encoding="utf-8")
        report_source = Path("native/cdmw_preview_core/src/owners/preview_report.cpp").read_text(encoding="utf-8")

        self.assertIn("resident_pathc_cache().swap(empty)", archive_source)
        self.assertIn("static void trim_resident_pathc_cache()", archive_source)
        self.assertIn("resident_technique_index_cache().swap(technique_indexes)", graph_source)
        self.assertIn("resident_package_technique_index_cache().swap(package_technique_indexes)", graph_source)
        self.assertIn("resident_native_material_graph_cache().swap(material_graphs)", graph_source)
        self.assertIn("static void trim_resident_material_graph_metadata()", graph_source)
        self.assertIn("resident_parsed_material_sidecar_cache().swap(empty)", sidecar_source)
        self.assertIn("static void trim_resident_parsed_material_sidecar_cache()", sidecar_source)
        # The cross-package basename scan cache must exist, cache negative
        # results, and invalidate against the on-disk .pamt set.
        self.assertIn("resident_cross_package_scan_cache", lookup_source)
        self.assertIn("cross_package_scan_signature", lookup_source)
        self.assertIn("release_resident_cross_package_scan_cache", lookup_source)
        release_start = report_source.index("static void release_resident_preview_metadata_caches()")
        release_body = report_source[release_start : report_source.index("static void trim_resident_preview_metadata_caches()", release_start)]
        self.assertIn("release_resident_pathc_cache()", release_body)
        self.assertIn("release_resident_material_graph_metadata()", release_body)
        self.assertIn("release_resident_parsed_material_sidecar_cache()", release_body)
        self.assertIn("release_resident_cross_package_scan_cache()", release_body)
        self.assertNotIn("decoded_entry_cache", release_body)
        trim_position = report_source.index("trim_resident_preview_metadata_caches();", release_start)
        memory_position = report_source.index("cdmw_native_diag::current_process_memory()")
        self.assertLess(trim_position, memory_position)
        self.assertIn("native_metadata_cache_resident_before_release", report_source)
        self.assertIn("native_metadata_cache_resident_after_release", report_source)
        self.assertIn("native_metadata_cache_released", report_source)
        catch_body = report_source[report_source.index("int run_preview_job(") :]
        self.assertIn("release_resident_preview_metadata_caches();", catch_body)

    def test_run_native_preview_core_job_removes_transient_paths(self) -> None:
        def fake_run_process(cmd, **_kwargs):
            report_path = Path(cmd[3])
            job = json.loads(Path(cmd[2]).read_text(encoding="utf-8"))
            report_path.write_text(
                json.dumps({"status": "ok", "package_path": job["output_root"]}),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_binary = temp_path / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=temp_path / "cache",
                    output_root=temp_path / "durable" / "package",
                    timeout_seconds=0.5,
                    use_service=False,
                )

        self.assertEqual("", attempt.report_path)
        self.assertEqual("", attempt.job_root_path)
        self.assertFalse(Path(str(attempt.diagnostics["native_preview_core_job_root"])).exists())


if __name__ == "__main__":
    unittest.main()
