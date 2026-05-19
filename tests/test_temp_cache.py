from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cdmw.core.temp_cache import (
    APP_TEMP_CACHE_ROOT_ENV,
    DEFAULT_APP_TEMP_CACHE_MAX_BYTES,
    DEFAULT_APP_TEMP_CACHE_TARGET_BYTES,
    app_temp_cache_path,
    app_temp_root,
    prune_app_temp_cache,
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
                app_temp_cache_path("directxtex_texture_preview", "abc"),
                configured_root / "directxtex_texture_preview" / "abc",
            )

    def test_prune_removes_oldest_managed_units_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            app_root = Path(temp_text) / "CrimsonDesertModWorkbench"
            old_unit = app_root / "archive_preview_cache" / "old"
            new_unit = app_root / "directxtex_texture_preview" / "new"
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


if __name__ == "__main__":
    unittest.main()
