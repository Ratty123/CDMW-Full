from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.rendering.native_preview_core import build_native_preview_core_job
from cdmw.ui.archive_browser.preview_cache import _archive_preview_dependency_digest


def _entry(path: str, *, prepared_sha256: str) -> ArchiveEntry:
    entry = ArchiveEntry(
        path=path,
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/1.paz"),
        offset=128,
        comp_size=64,
        orig_size=64,
        flags=0,
        paz_index=1,
    )
    entry.prepared_path = Path("C:/cache/prepared") / Path(path).name
    entry.prepared_sha256 = prepared_sha256
    return entry


class ArchivePreviewDependencyOptimizationTests(unittest.TestCase):
    def test_native_job_carries_complete_prepared_dependency_snapshot(self) -> None:
        selected = _entry(
            "character/model/example/cd_example.pac",
            prepared_sha256=hashlib.sha256(b"selected").hexdigest(),
        )
        texture = _entry(
            "character/texture/example/cd_example_d.dds",
            prepared_sha256=hashlib.sha256(b"texture").hexdigest(),
        )

        job = build_native_preview_core_job(
            selected,
            cache_root=Path("C:/cache/native"),
            output_root=Path("C:/cache/package"),
            dependency_entries=(selected, texture),
            dependency_entries_complete=True,
        )

        self.assertTrue(job["archive_dependency_entries_complete"])
        self.assertEqual(2, len(job["archive_dependency_entries"]))
        self.assertEqual(str(selected.prepared_path), job["entry"]["prepared_path"])
        self.assertEqual(texture.prepared_sha256, job["archive_dependency_entries"][1]["prepared_sha256"])

    def test_dependency_digest_is_order_independent_and_hash_sensitive(self) -> None:
        first = _entry("a/model.pac", prepared_sha256="1" * 64)
        second = _entry("b/material.dds", prepared_sha256="2" * 64)
        baseline = _archive_preview_dependency_digest((first, second))

        self.assertEqual(baseline, _archive_preview_dependency_digest((second, first)))
        second.prepared_sha256 = "3" * 64
        self.assertNotEqual(baseline, _archive_preview_dependency_digest((first, second)))

    def test_incomplete_dependency_hash_disables_snapshot_cache_identity(self) -> None:
        entry = _entry("a/model.pac", prepared_sha256="")

        self.assertEqual("", _archive_preview_dependency_digest((entry,)))

    def test_complete_native_snapshot_requires_a_bounded_selected_entry(self) -> None:
        selected = _entry("a/model.pac", prepared_sha256="1" * 64)

        with self.assertRaisesRegex(ValueError, "selected entry"):
            build_native_preview_core_job(
                selected,
                cache_root=Path("C:/cache/native"),
                output_root=Path("C:/cache/package"),
                dependency_entries_complete=True,
            )
        with self.assertRaisesRegex(ValueError, "4,096"):
            build_native_preview_core_job(
                selected,
                cache_root=Path("C:/cache/native"),
                output_root=Path("C:/cache/package"),
                dependency_entries=(selected,) * 4097,
            )

    def test_native_lookup_uses_bounded_snapshot_before_legacy_package_scan(self) -> None:
        source_path = Path("native/cdmw_preview_core/src/owners/material_archive_lookup.cpp")
        source = source_path.read_text(encoding="utf-8")
        basename_start = source.index("lookup_basename_candidates_across_package")
        basename_end = source.index("resolve_archive_path_across_package", basename_start)
        basename_lookup = source[basename_start:basename_end]

        self.assertLess(
            basename_lookup.index("lookup_bounded_archive_dependency_basename"),
            basename_lookup.index("lookup_archive_lite_basename"),
        )
        self.assertIn("return result;", basename_lookup)
        self.assertIn("package_root_pamt_paths", basename_lookup)

        decode_source = Path("native/cdmw_preview_core/src/owners/archive_decode.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("entry.prepared_path.empty()", decode_source)
        self.assertIn("read_binary_file(entry.prepared_path)", decode_source)

    def test_reference_preview_reuses_the_prepared_v2_snapshot(self) -> None:
        source = Path("cdmw/ui/archive_browser/reference_preview.py").read_text(encoding="utf-8")
        start = source.index("def _open_archive_reference_preview_entry")
        end = source.index("def _export_selected_archive_texture_reference", start)
        implementation = source[start:end]

        self.assertIn("prepared_dependencies_for(resolved_entry)", implementation)
        self.assertIn("dependency_entries=dependency_entries", implementation)
        self.assertIn("dependency_entries_complete=remote_dependencies is not None", implementation)


if __name__ == "__main__":
    unittest.main()
