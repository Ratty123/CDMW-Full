from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.mesh_editor_source_support import mesh_editor_tab_source

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.rendering.native_preview_package_cache import (
    NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA,
    create_native_preview_package_staging_dir,
    acquire_native_preview_package_cache_lease_for_path,
    lookup_native_preview_package_cache,
    native_preview_package_cache_use,
    prune_native_preview_package_cache,
    release_native_preview_package_staging_dir,
    store_native_preview_package_cache,
)
from cdmw.workers.archive_preview_native import ArchivePreviewNativeMixin
from cdmw.workers.d3d11_package_workers import ArchiveNativePreviewPrefetchWorker


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/example.pac",
        pamt_path=Path("example.pamt"),
        paz_file=Path("example.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def _validate(package_dir: Path):
    return (package_dir / "manifest.json").is_file(), ()


def _raw_cache_entry(cache_root: Path, key: str) -> Path:
    entry_dir = cache_root / "packages" / key
    package_dir = entry_dir / "package"
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (package_dir / "payload.bin").write_bytes(b"x" * 64)
    (entry_dir / "cache_entry.json").write_text(
        json.dumps(
            {
                "schema": NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA,
                "cache_key": key,
                "last_access_ns": 1,
            }
        ),
        encoding="utf-8",
    )
    return entry_dir


class NativePreviewPackageCacheConcurrencyTests(unittest.TestCase):
    def test_same_key_prefetch_builds_once_across_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            started = threading.Event()
            release = threading.Event()
            start_barrier = threading.Barrier(3)
            build_count = 0
            count_lock = threading.Lock()

            def fake_build(_entry, **kwargs):
                nonlocal build_count
                with count_lock:
                    build_count += 1
                output_root = Path(kwargs["output_root"])
                output_root.mkdir(parents=True)
                (output_root / "manifest.json").write_text("{}", encoding="utf-8")
                started.set()
                self.assertTrue(release.wait(5.0))
                return NativePreviewCoreAttempt(status="ok", package_path=str(output_root))

            workers = [
                ArchiveNativePreviewPrefetchWorker(
                    ((_entry(), None, "same-key"),),
                    None,
                    cache_root,
                    None,
                    "aggressive",
                    1024 * 1024,
                    512 * 1024,
                    validate_package=_validate,
                )
                for _index in range(2)
            ]

            def run(worker: ArchiveNativePreviewPrefetchWorker) -> None:
                start_barrier.wait()
                worker.run()

            with patch(
                "cdmw.workers.d3d11_package_workers.run_native_preview_core_preview_job",
                side_effect=fake_build,
            ):
                threads = [threading.Thread(target=run, args=(worker,)) for worker in workers]
                for thread in threads:
                    thread.start()
                start_barrier.wait()
                self.assertTrue(started.wait(5.0))
                self.assertEqual(1, build_count)
                release.set()
                for thread in threads:
                    thread.join(5.0)
                    self.assertFalse(thread.is_alive())

            self.assertEqual(1, build_count)
            self.assertIsNotNone(
                lookup_native_preview_package_cache(
                    cache_root,
                    "same-key",
                    validate_package=_validate,
                )
            )

    def test_concurrent_publication_keeps_one_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            barrier = threading.Barrier(3)
            stages = []
            results = []
            for marker in ("first", "second"):
                staging = cache_root / "packages" / f"_staging_{marker}"
                package = staging / "package"
                package.mkdir(parents=True)
                (package / "manifest.json").write_text("{}", encoding="utf-8")
                (package / "winner.txt").write_text(marker, encoding="utf-8")
                stages.append(staging)

            def publish(staging: Path) -> None:
                barrier.wait()
                results.append(
                    store_native_preview_package_cache(
                        cache_root,
                        "shared",
                        staging,
                        {},
                        validate_package=_validate,
                        max_bytes=1024 * 1024,
                        target_bytes=512 * 1024,
                    )
                )

            threads = [threading.Thread(target=publish, args=(staging,)) for staging in stages]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(5.0)
                self.assertFalse(thread.is_alive())

            self.assertEqual(2, len(results))
            self.assertTrue(all(hit is not None for hit in results))
            final_package = cache_root / "packages" / "shared" / "package"
            self.assertIn((final_package / "winner.txt").read_text(encoding="utf-8"), {"first", "second"})
            self.assertTrue((final_package / "manifest.json").is_file())
            self.assertTrue(all(not staging.exists() for staging in stages))

    def test_publication_repairs_invalid_recent_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            stale_entry = _raw_cache_entry(cache_root, "recent-invalid")
            self.assertIsNotNone(
                lookup_native_preview_package_cache(
                    cache_root,
                    "recent-invalid",
                    validate_package=_validate,
                )
            )
            (stale_entry / "package" / "manifest.json").unlink()
            staging = create_native_preview_package_staging_dir(cache_root)
            package = staging / "package"
            package.mkdir()
            (package / "manifest.json").write_text('{"replacement":true}', encoding="utf-8")

            hit = store_native_preview_package_cache(
                cache_root,
                "recent-invalid",
                staging,
                {},
                validate_package=_validate,
                max_bytes=1024 * 1024,
                target_bytes=512 * 1024,
            )

            self.assertIsNotNone(hit)
            self.assertTrue((stale_entry / "package" / "manifest.json").is_file())
            self.assertIn("replacement", (stale_entry / "package" / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(staging.exists())

    def test_foreground_build_preserves_complete_package_when_cache_entry_is_active_and_invalid(self) -> None:
        class Harness(ArchivePreviewNativeMixin):
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            active_entry = _raw_cache_entry(cache_root, "active-invalid")
            (active_entry / "package" / "manifest.json").unlink()
            harness = Harness()
            harness.native_preview_core_enabled = True
            harness.entry = _entry()
            harness.native_preview_core_cache_root = cache_root
            harness.native_preview_package_cache_mode = "balanced"
            harness.native_preview_package_cache_key = "active-invalid"
            harness.native_preview_package_cache_max_bytes = 1024 * 1024
            harness.native_preview_package_cache_target_bytes = 512 * 1024
            harness.render_settings = None
            harness.companion_entry = None
            harness.native_preview_core_package_root = None
            harness.native_preview_dependency_entries = ()
            harness.native_preview_dependency_entries_complete = False
            harness.enabled_prefab_component_paths = ()
            harness.stop_event = threading.Event()

            def fake_build(_entry, **kwargs):
                output_root = Path(kwargs["output_root"])
                output_root.mkdir(parents=True)
                (output_root / "manifest.json").write_text("{}", encoding="utf-8")
                return NativePreviewCoreAttempt(status="ok", package_path=str(output_root))

            with (
                native_preview_package_cache_use(cache_root, "active-invalid"),
                patch(
                    "cdmw.workers.archive_preview_native.run_native_preview_core_preview_job",
                    side_effect=fake_build,
                ),
            ):
                attempt = harness._try_native_preview_core()

            self.assertIsNotNone(attempt)
            self.assertTrue(attempt.succeeded)  # type: ignore[union-attr]
            package_dir = Path(attempt.package_path)  # type: ignore[union-attr]
            self.assertTrue((package_dir / "manifest.json").is_file())
            self.assertTrue(package_dir.parent.name.startswith("cdmw_preview_core_"))
            self.assertEqual(
                "standalone_fallback",
                attempt.diagnostics["native_preview_package_cache"],  # type: ignore[union-attr]
            )
            release_native_preview_package_staging_dir(package_dir.parent, cleanup=True)

    def test_prune_skips_active_staging_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            staging = create_native_preview_package_staging_dir(cache_root, leased=True)
            (staging / "writing.bin").write_bytes(b"x" * 64)

            prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)

            self.assertTrue(staging.is_dir())
            release_native_preview_package_staging_dir(staging, cleanup=True)
            self.assertFalse(staging.exists())

    def test_prune_skips_explicitly_used_and_just_returned_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            active_entry = _raw_cache_entry(cache_root, "active")
            recent_entry = _raw_cache_entry(cache_root, "recent")
            old_entry = _raw_cache_entry(cache_root, "old")
            recent_hit = lookup_native_preview_package_cache(
                cache_root,
                "recent",
                validate_package=_validate,
            )
            self.assertIsNotNone(recent_hit)

            with native_preview_package_cache_use(cache_root, "active"):
                prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)
                self.assertTrue(active_entry.is_dir())

            self.assertTrue(recent_entry.is_dir())
            self.assertFalse(old_entry.exists())

    def test_path_lease_stays_pinned_until_renderer_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            active_entry = _raw_cache_entry(cache_root, "active")
            old_entry = _raw_cache_entry(cache_root, "old")
            lease = acquire_native_preview_package_cache_lease_for_path(active_entry / "package")
            self.assertIsNotNone(lease)

            prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)
            self.assertTrue(active_entry.is_dir())
            self.assertFalse(old_entry.exists())

            lease.release()  # type: ignore[union-attr]
            prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)
            self.assertFalse(active_entry.exists())

    def test_path_lease_acquisition_uses_the_same_key_lock_as_pruning(self) -> None:
        source = Path("cdmw/rendering/native_preview_package_cache.py").read_text(encoding="utf-8")
        start = source.index("def acquire_native_preview_package_cache_lease_for_path(")
        body = source[start : source.index("def is_temp_native_preview_package_path", start)]
        self.assertIn("with native_preview_package_cache_build_lock(cache_root, cache_key):", body)
        self.assertIn("if not package_path.is_dir():", body)

        runtime = Path("cdmw/ui/mesh_editor/native_preview_runtime.py").read_text(encoding="utf-8")
        tab = mesh_editor_tab_source()
        self.assertIn('getattr(host_widget, "hold_native_preview_package_cache_lease", None)', runtime)
        self.assertIn('getattr(host, "track_renderer_process", None)', tab)
        self.assertIn('"retain_native_preview_package_cache_lease"', tab)

    def test_renderer_host_owns_lease_across_reload_and_cancel(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            first_entry = _raw_cache_entry(cache_root, "first")
            second_entry = _raw_cache_entry(cache_root, "second")
            host = NativeD3D11PreviewHostFrame()
            host._send_host_json_command = lambda _payload: True  # type: ignore[method-assign]
            try:
                self.assertTrue(host.load_package(first_entry / "package", first_entry / "status.json"))
                self.assertTrue(host.load_package(second_entry / "package", second_entry / "status.json"))
                host.retain_native_preview_package_cache_lease(second_entry / "package")

                prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)
                self.assertFalse(first_entry.exists())
                self.assertTrue(second_entry.is_dir())

                host.release_native_preview_package_cache_leases()
                prune_native_preview_package_cache(cache_root, max_bytes=1, target_bytes=0)
                self.assertFalse(second_entry.exists())
            finally:
                host.close()
                host.deleteLater()
                app.processEvents()

    def test_archive_renderer_cleanup_leaves_durable_cache_for_pruner(self) -> None:
        from cdmw.ui.archive_browser.preview_d3d11_process import ArchivePreviewD3D11ProcessMixin

        class Harness(ArchivePreviewD3D11ProcessMixin):
            def __init__(self, cache_root: Path) -> None:
                self.cache_root = cache_root

            def _native_preview_package_cache_root(self) -> Path:
                return self.cache_root

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            entry = _raw_cache_entry(cache_root, "durable")

            Harness(cache_root)._remove_archive_isolated_package_dir(entry / "package")

            self.assertTrue(entry.is_dir())
            self.assertTrue((entry / "package" / "manifest.json").is_file())

    def test_cancelled_prefetch_removes_leased_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            worker = ArchiveNativePreviewPrefetchWorker(
                ((_entry(), None, "cancelled"),),
                None,
                cache_root,
                None,
                "aggressive",
                1024 * 1024,
                512 * 1024,
                validate_package=_validate,
            )
            with patch(
                "cdmw.workers.d3d11_package_workers.run_native_preview_core_preview_job",
                side_effect=RunCancelled("cancelled"),
            ):
                worker.run()

            packages_root = cache_root / "packages"
            self.assertEqual((), tuple(packages_root.glob("_staging_*")))

    def test_cancelled_foreground_build_removes_leased_staging(self) -> None:
        class Harness(ArchivePreviewNativeMixin):
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            harness = Harness()
            harness.native_preview_core_enabled = True
            harness.entry = _entry()
            harness.native_preview_core_cache_root = cache_root
            harness.native_preview_package_cache_mode = "balanced"
            harness.native_preview_package_cache_key = "cancelled"
            harness.native_preview_package_cache_max_bytes = 1024 * 1024
            harness.native_preview_package_cache_target_bytes = 512 * 1024
            harness.render_settings = None
            harness.companion_entry = None
            harness.native_preview_core_package_root = None
            harness.stop_event = threading.Event()
            with (
                patch(
                    "cdmw.workers.archive_preview_native.run_native_preview_core_preview_job",
                    side_effect=RunCancelled("cancelled"),
                ),
                self.assertRaises(RunCancelled),
            ):
                harness._try_native_preview_core()

            packages_root = cache_root / "packages"
            self.assertEqual((), tuple(packages_root.glob("_staging_*")))


if __name__ == "__main__":
    unittest.main()
