from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from cdmw.core import archive_media_preview
from cdmw.core.temp_cache import (
    APP_TEMP_CACHE_ROOT_ENV,
    mark_app_temp_cache_recent,
    prune_app_temp_cache,
)
from cdmw.models import ArchiveEntry


def _entry(root: Path) -> ArchiveEntry:
    package = root / "0001"
    package.mkdir(parents=True)
    pamt_path = package / "0.pamt"
    paz_path = package / "0.paz"
    pamt_path.write_bytes(b"pamt")
    paz_path.write_bytes(b"paz")
    return ArchiveEntry(
        "ui/texture/sample.bin",
        pamt_path,
        paz_path,
        0,
        15,
        15,
        0,
        0,
    )


class ArchiveMediaPreviewCacheTests(unittest.TestCase):
    def test_same_key_concurrent_extract_runs_archive_reader_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            cache_root = root / "cache"
            entry = _entry(root)
            calls = 0
            calls_lock = threading.Lock()

            def read_once(_entry: ArchiveEntry, *, stop_event: object = None) -> tuple[bytes, bool, str]:
                del _entry, stop_event
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.05)
                return b"archive payload", False, "archive note"

            with (
                mock.patch.dict(os.environ, {APP_TEMP_CACHE_ROOT_ENV: str(cache_root)}),
                mock.patch.object(archive_media_preview, "read_archive_entry_data", side_effect=read_once),
                mock.patch.object(archive_media_preview, "request_app_temp_cache_prune", return_value=None),
            ):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(lambda _index: archive_media_preview.ensure_archive_preview_source(entry), range(8)))
                cached_again = archive_media_preview.ensure_archive_preview_source(entry)

            paths = {result[0] for result in results}
            self.assertEqual(1, calls)
            self.assertEqual(1, len(paths))
            self.assertEqual((next(iter(paths)), "archive note"), cached_again)
            self.assertEqual(b"archive payload", cached_again[0].read_bytes())
            self.assertEqual("archive note", (cached_again[0].parent / ".note").read_text(encoding="utf-8"))
            self.assertFalse(any(path.name.endswith(".staging") for path in cached_again[0].parent.parent.iterdir()))

    def test_failed_publication_leaves_no_partial_or_staging_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            cache_root = root / "cache"
            entry = _entry(root)

            with (
                mock.patch.dict(os.environ, {APP_TEMP_CACHE_ROOT_ENV: str(cache_root)}),
                mock.patch.object(
                    archive_media_preview,
                    "read_archive_entry_data",
                    return_value=(b"archive payload", False, "archive note"),
                ),
                mock.patch.object(archive_media_preview, "atomic_publish_directory", side_effect=OSError("publish failed")),
            ):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    archive_media_preview.ensure_archive_preview_source(entry)

            cache_parent = cache_root / "archive_preview_cache"
            self.assertEqual((), tuple(cache_parent.iterdir()) if cache_parent.is_dir() else ())

    def test_just_returned_archive_preview_survives_immediate_prune(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            cache_root = root / "cache"
            entry = _entry(root)

            with (
                mock.patch.dict(os.environ, {APP_TEMP_CACHE_ROOT_ENV: str(cache_root)}),
                mock.patch.object(
                    archive_media_preview,
                    "read_archive_entry_data",
                    return_value=(b"x" * 700, False, ""),
                ),
                mock.patch.object(archive_media_preview, "request_app_temp_cache_prune", return_value=None),
            ):
                preview_path, _note = archive_media_preview.ensure_archive_preview_source(entry)

            protected = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=cache_root)
            self.assertEqual(0, protected.removed_units)
            self.assertTrue(preview_path.is_file())

            mark_app_temp_cache_recent(preview_path, seconds=0)
            removed = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=cache_root)
            self.assertEqual(1, removed.removed_units)
            self.assertFalse(preview_path.exists())


if __name__ == "__main__":
    unittest.main()
