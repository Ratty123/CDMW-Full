from __future__ import annotations

import gc
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cdmw.core.temp_cache as temp_cache
from cdmw.core.temp_cache import (
    APP_TEMP_CACHE_ROOT_ENV,
    AppTempCachePruneReport,
    DEFAULT_APP_TEMP_CACHE_MAX_BYTES,
    DEFAULT_APP_TEMP_CACHE_TARGET_BYTES,
    DIRECTXTEX_TEXTURE_PREVIEW_CACHE_DIRNAME,
    app_temp_cache_build,
    app_temp_cache_path,
    app_temp_root,
    app_temp_cache_use,
    prune_app_temp_cache,
    request_app_temp_cache_prune,
)


class AppTempCacheTests(unittest.TestCase):
    def test_default_temp_cache_cap_stays_below_one_gb(self) -> None:
        self.assertEqual(DEFAULT_APP_TEMP_CACHE_MAX_BYTES, 512 * 1024 * 1024)
        self.assertEqual(DEFAULT_APP_TEMP_CACHE_TARGET_BYTES, 384 * 1024 * 1024)

    def test_app_temp_cache_path_uses_app_named_temp_root(self) -> None:
        root = Path("C:/temp_root")
        path = app_temp_cache_path("preview_cache", "abc", temp_root=root)

        self.assertEqual(path, root / "CrimsonDesertModWorkbench" / "preview_cache" / "abc")

    def test_app_temp_root_prefers_configured_cache_root(self) -> None:
        configured_root = Path(tempfile.gettempdir()) / "cdmw_test_archive_cache"

        with mock.patch.dict(os.environ, {APP_TEMP_CACHE_ROOT_ENV: str(configured_root)}):
            self.assertEqual(app_temp_root(), configured_root)
            self.assertEqual(
                app_temp_cache_path(DIRECTXTEX_TEXTURE_PREVIEW_CACHE_DIRNAME, "abc"),
                configured_root / "preview" / "textures" / "directxtex" / "abc",
            )

    def test_prune_removes_oldest_managed_units_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            app_root = Path(temp_text) / "CrimsonDesertModWorkbench"
            old_unit = app_root / "archive_preview_cache" / "old"
            new_unit = app_root / DIRECTXTEX_TEXTURE_PREVIEW_CACHE_DIRNAME / "new"
            foreign_unit = app_root / "not_a_managed_cache" / "foreign"
            old_unit.mkdir(parents=True)
            new_unit.mkdir(parents=True)
            foreign_unit.mkdir(parents=True)
            (old_unit / "entry.dds").write_bytes(b"a" * 700)
            (new_unit / "preview.png").write_bytes(b"b" * 700)
            (foreign_unit / "keep.bin").write_bytes(b"c" * 2000)
            os.utime(old_unit / "entry.dds", (100.0, 100.0))
            os.utime(new_unit / "preview.png", (200.0, 200.0))

            report = prune_app_temp_cache(max_bytes=1000, target_bytes=700, root=app_root)

            self.assertEqual(report.total_bytes_before, 1400)
            self.assertEqual(report.total_bytes_after, 700)
            self.assertEqual(report.removed_units, 1)
            self.assertFalse(old_unit.exists())
            self.assertTrue(new_unit.exists())
            self.assertTrue(foreign_unit.exists())

    def test_prune_skips_cache_unit_while_build_lease_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            app_root = Path(temp_text) / "CrimsonDesertModWorkbench"
            unit = app_root / "archive_preview_cache" / "building"
            unit.mkdir(parents=True)
            (unit / "payload.bin").write_bytes(b"x" * 700)
            started = threading.Event()
            release = threading.Event()

            def hold_build() -> None:
                with app_temp_cache_build(unit):
                    started.set()
                    self.assertTrue(release.wait(5.0))

            thread = threading.Thread(target=hold_build)
            thread.start()
            self.assertTrue(started.wait(5.0))
            report = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=app_root)

            self.assertEqual(0, report.removed_units)
            self.assertTrue(unit.is_dir())
            release.set()
            thread.join(5.0)
            self.assertFalse(thread.is_alive())

            prune_app_temp_cache(max_bytes=1, target_bytes=0, root=app_root)
            self.assertFalse(unit.exists())

    def test_prune_skips_cache_unit_while_descendant_read_lease_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            app_root = Path(temp_text) / "CrimsonDesertModWorkbench"
            unit = app_root / "preview_cache" / "reading"
            payload = unit / "preview.png"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"x" * 700)
            started = threading.Event()
            release = threading.Event()

            def hold_read() -> None:
                with app_temp_cache_use(payload):
                    started.set()
                    self.assertTrue(release.wait(5.0))

            thread = threading.Thread(target=hold_read)
            thread.start()
            self.assertTrue(started.wait(5.0))
            report = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=app_root)

            self.assertEqual(0, report.removed_units)
            self.assertEqual(b"x" * 700, payload.read_bytes())
            release.set()
            thread.join(5.0)
            self.assertFalse(thread.is_alive())

            prune_app_temp_cache(max_bytes=1, target_bytes=0, root=app_root)
            self.assertFalse(unit.exists())

    def test_cache_unit_lock_registry_releases_unused_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "CrimsonDesertModWorkbench" / "preview_cache"
            baseline = len(temp_cache._CACHE_UNIT_LOCKS)
            for index in range(1000):
                lock = temp_cache._cache_unit_lock(root / str(index))
            del lock
            gc.collect()

            self.assertLessEqual(len(temp_cache._CACHE_UNIT_LOCKS), baseline + 1)

    def test_prune_request_never_scans_on_caller_thread(self) -> None:
        started = threading.Event()
        release = threading.Event()
        worker_threads: list[int] = []

        def slow_prune(**_kwargs: object) -> AppTempCachePruneReport:
            worker_threads.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(5.0))
            return AppTempCachePruneReport(0, 0, 0, 0, 0, 0)

        self.assertTrue(temp_cache._PRUNE_LOCK.acquire(timeout=5.0))
        temp_cache._PRUNE_LOCK.release()
        previous = temp_cache._last_prune_monotonic
        temp_cache._last_prune_monotonic = 0.0
        try:
            with mock.patch.object(temp_cache, "prune_app_temp_cache", side_effect=slow_prune):
                before = time.perf_counter()
                self.assertIsNone(request_app_temp_cache_prune(min_interval_seconds=0.0))
                self.assertLess(time.perf_counter() - before, 0.05)
                self.assertTrue(started.wait(1.0))
                self.assertIsNone(request_app_temp_cache_prune(min_interval_seconds=0.0))
                self.assertEqual([worker_threads[0]], worker_threads)
                self.assertNotEqual(threading.get_ident(), worker_threads[0])
                release.set()
                self.assertTrue(temp_cache._PRUNE_LOCK.acquire(timeout=5.0))
                temp_cache._PRUNE_LOCK.release()
        finally:
            release.set()
            temp_cache._last_prune_monotonic = previous


if __name__ == "__main__":
    unittest.main()
