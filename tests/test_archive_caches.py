from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from cdmw.core import archive_accelerator as archive_accel, archive_scan_cache
from cdmw.core.archive import (
    _ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
    _ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
    _ARCHIVE_SCAN_CACHE_MAGIC,
    _ARCHIVE_SIDECAR_CACHE_MAGIC,
    _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
    _collect_archive_scan_sources,
    _collect_archive_scan_sources_from_entries,
    _deserialize_archive_derived_index_cache_payload_from_path,
    _deserialize_cache_payload_from_path,
    _read_archive_name_search_shard_meta,
    _write_archive_name_search_shard_meta,
    _write_raw_pickle_cache_payload_to_path,
    _write_native_name_search_index_binary,
    _build_archive_entry_cache_signatures,
    build_archive_entry_basename_index,
    build_archive_entry_extension_index,
    build_archive_entry_path_index,
    build_archive_entry_role_index,
    build_archive_name_search_index,
    archive_scan_shard_cache_health,
    load_archive_item_icon_thumbnail_cache,
    load_or_update_archive_basic_index_shards,
    load_or_update_archive_scan_shards,
    load_archive_basic_index_cache,
    load_archive_derived_index_cache,
    load_archive_scan_cache,
    load_archive_texture_sidecar_cache_rows,
    load_or_update_archive_name_search_shards,
    invalidate_archive_browser_cache,
    prune_archive_cache_root,
    resolve_archive_basic_index_cache_path,
    resolve_archive_basic_index_shard_cache_dir,
    resolve_archive_scan_cache_path,
    resolve_archive_scan_shard_cache_dir,
    resolve_archive_name_search_index_cache_path,
    resolve_archive_name_search_shard_cache_dir,
    resolve_archive_derived_index_cache_path,
    resolve_archive_item_icon_thumbnail_cache_dir,
    resolve_archive_sidecar_cache_path,
    save_archive_basic_index_cache,
    save_archive_derived_index_cache,
    save_archive_item_icon_thumbnail_cache,
    save_archive_scan_cache,
    save_archive_texture_sidecar_cache,
    scan_archive_entries,
)
from cdmw.core.table_catalog import table_catalog_cache_metadata
from cdmw.models import ArchiveEntry


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_entry_files(root: Path, group: str, data: bytes) -> tuple[Path, Path]:
    group_root = root / group
    group_root.mkdir(parents=True, exist_ok=True)
    pamt_path = group_root / "0.pamt"
    paz_path = group_root / "0.paz"
    pamt_path.write_bytes(b"pamt")
    paz_path.write_bytes(data)
    return pamt_path, paz_path


def _entry(path: str, pamt_path: Path, paz_path: Path, data: bytes) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=len(data),
        orig_size=len(data),
        flags=0,
        paz_index=0,
    )


def _sidecar_text(texture_path: str, *, extra: str = "") -> bytes:
    return (
        f'<SkinnedMeshMaterialWrapper><MaterialParameterTexture _name="_normalTexture">'
        f'<ResourceReferencePath_ITexture _path="{texture_path}"/>'
        f"</MaterialParameterTexture>{extra}</SkinnedMeshMaterialWrapper>"
    ).encode("utf-8")


class ArchiveCacheTests(unittest.TestCase):
    def test_native_archive_accelerator_readiness_is_memoized_by_file_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "cdmw-archive-accelerator"
            binary.write_bytes(b"native helper")
            archive_accel._ARCHIVE_ACCELERATOR_VERSION_CACHE.clear()
            try:
                with mock.patch.object(
                    archive_accel,
                    "_archive_accelerator_version",
                    return_value=archive_accel.ARCHIVE_ACCELERATOR_PROTOCOL,
                ) as version:
                    self.assertTrue(archive_accel._native_archive_accelerator_ready(binary))
                    self.assertTrue(archive_accel._native_archive_accelerator_ready(binary))
                    self.assertEqual(version.call_count, 1)

                    binary.write_bytes(b"native helper changed")
                    self.assertTrue(archive_accel._native_archive_accelerator_ready(binary))
                    self.assertEqual(version.call_count, 2)
            finally:
                archive_accel._ARCHIVE_ACCELERATOR_VERSION_CACHE.clear()

    def test_native_archive_accelerator_readiness_none_is_false_without_version_call(self) -> None:
        archive_accel._ARCHIVE_ACCELERATOR_VERSION_CACHE.clear()
        with mock.patch.object(
            archive_accel,
            "_archive_accelerator_version",
            side_effect=AssertionError("None accelerator must not launch --version"),
        ):
            self.assertFalse(archive_accel._native_archive_accelerator_ready(None))

    def test_native_archive_accelerator_readiness_missing_binary_falls_back_to_uncached_version_check(self) -> None:
        archive_accel._ARCHIVE_ACCELERATOR_VERSION_CACHE.clear()
        with mock.patch.object(archive_accel, "_archive_accelerator_version", return_value=None) as version:
            self.assertFalse(archive_accel._native_archive_accelerator_ready(Path("definitely-missing-accelerator")))
            self.assertEqual(version.call_count, 1)

    def test_item_icon_thumbnail_cache_round_trip_and_converter_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"DDS icon"
            pamt, paz = _write_entry_files(root, "0009", data)
            entry = _entry("ui/itemicon/itemicon_test.dds", pamt, paz, data)
            thumbnail = root / "thumb.png"
            thumbnail.write_bytes(b"png")
            icon_paths = ("ui/itemicon/itemicon_test.dds",)

            saved = save_archive_item_icon_thumbnail_cache(
                root,
                cache_root,
                icon_paths,
                entry,
                thumbnail,
                size=120,
                converter_key="native=v1",
                note="Recovered inventory icon: ui/itemicon/itemicon_test.dds",
            )

            loaded = load_archive_item_icon_thumbnail_cache(
                root,
                cache_root,
                icon_paths,
                entry,
                size=120,
                converter_key="native=v1",
            )
            self.assertIsNotNone(loaded)
            loaded_path, loaded_note = loaded or (Path(), "")
            self.assertEqual(saved, loaded_path)
            self.assertIn("Recovered inventory icon", loaded_note)
            manifest = resolve_archive_item_icon_thumbnail_cache_dir(root, cache_root) / "manifest.json"
            self.assertTrue(manifest.is_file())
            with mock.patch("cdmw.core.archive._write_archive_item_icon_thumbnail_manifest") as write_manifest:
                loaded_again = load_archive_item_icon_thumbnail_cache(
                    root,
                    cache_root,
                    icon_paths,
                    entry,
                    size=120,
                    converter_key="native=v1",
                )
            self.assertIsNotNone(loaded_again)
            write_manifest.assert_not_called()

            self.assertIsNone(
                load_archive_item_icon_thumbnail_cache(
                    root,
                    cache_root,
                    icon_paths,
                    entry,
                    size=120,
                    converter_key="native=v2",
                )
            )

    def test_item_icon_thumbnail_cache_misses_when_entry_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"DDS icon"
            pamt, paz = _write_entry_files(root, "0009", data)
            entry = _entry("ui/itemicon/itemicon_test.dds", pamt, paz, data)
            thumbnail = root / "thumb.png"
            thumbnail.write_bytes(b"png")
            icon_paths = ("ui/itemicon/itemicon_test.dds",)
            save_archive_item_icon_thumbnail_cache(
                root,
                cache_root,
                icon_paths,
                entry,
                thumbnail,
                size=120,
                converter_key="native=v1",
            )

            changed = _entry("ui/itemicon/itemicon_test.dds", pamt, paz, data)
            changed.offset = 4

            self.assertIsNone(
                load_archive_item_icon_thumbnail_cache(
                    root,
                    cache_root,
                    icon_paths,
                    changed,
                    size=120,
                    converter_key="native=v1",
                )
            )

    def test_archive_cache_invalidation_removes_item_icon_thumbnail_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"DDS icon"
            pamt, paz = _write_entry_files(root, "0009", data)
            entry = _entry("ui/itemicon/itemicon_test.dds", pamt, paz, data)
            thumbnail = root / "thumb.png"
            thumbnail.write_bytes(b"png")
            save_archive_item_icon_thumbnail_cache(
                root,
                cache_root,
                ("ui/itemicon/itemicon_test.dds",),
                entry,
                thumbnail,
                size=120,
                converter_key="native=v1",
            )
            cache_dir = resolve_archive_item_icon_thumbnail_cache_dir(root, cache_root)
            self.assertTrue(cache_dir.is_dir())

            deleted = invalidate_archive_browser_cache(root, cache_root)

            self.assertIn(cache_dir, deleted)
            self.assertFalse(cache_dir.exists())

    def test_missing_generated_pamt_source_is_skipped_for_cache_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_pamt = root / "0037" / "0.pamt"
            _base, sources = _collect_archive_scan_sources_from_entries(
                root,
                [_entry("character/model/a.pac", missing_pamt, missing_pamt.with_suffix(".paz"), b"")],
            )

            self.assertEqual(sources, [])

    def test_scan_skips_missing_generated_pamt_without_worker_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_pamt = root / "0038" / "0.pamt"
            logs: list[str] = []

            with mock.patch("cdmw.core.archive.discover_pamt_files", return_value=[missing_pamt]):
                entries = scan_archive_entries(root, on_log=logs.append)

            self.assertEqual(entries, [])
            self.assertTrue(any("Skipped missing archive index" in line for line in logs))

    def test_load_or_update_archive_scan_shards_discovers_pamt_files_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]

            with mock.patch(
                "cdmw.core.archive_scan_cache.discover_pamt_files",
                wraps=archive_scan_cache.discover_pamt_files,
            ) as discover:
                loaded_entries, _source, _cache_dir = load_or_update_archive_scan_shards(
                    root,
                    cache_root,
                    shard_scan_func=lambda _path: entries,
                )

            self.assertEqual([entry.path for entry in loaded_entries], ["character/model/a.pac"])
            self.assertEqual(discover.call_count, 1)

    def test_archive_scan_shard_cache_health_discovers_pamt_files_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries)

            with mock.patch(
                "cdmw.core.archive_scan_cache.discover_pamt_files",
                wraps=archive_scan_cache.discover_pamt_files,
            ) as discover:
                health = archive_scan_shard_cache_health(root, cache_root, deep=True)

            self.assertEqual("healthy", health["status"])
            self.assertEqual(discover.call_count, 1)

    def test_archive_scan_cache_v2_is_rejected_after_native_scan_scope_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "game"
            cache_root = Path(temp_dir) / "cache"
            data = b"payload"
            _pamt, _paz = _write_entry_files(root, "0000", data)
            _base, sources = _collect_archive_scan_sources(root)
            cache_path = resolve_archive_scan_cache_path(root, cache_root)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            _write_raw_pickle_cache_payload_to_path(
                cache_path,
                magic=_ARCHIVE_SCAN_CACHE_MAGIC,
                payload={
                    "version": 2,
                    "package_root": str(root),
                    "created_at": 0.0,
                    "sources": sources,
                    "rows": [("character/model/a.pac", "0000/0.pamt", 0, len(data), len(data), 0, 0)],
                },
            )
            logs: list[str] = []

            entries = load_archive_scan_cache(root, cache_root, on_log=logs.append)

            self.assertIsNone(entries)
            self.assertTrue(any("format changed" in line for line in logs))
            self.assertFalse(cache_path.exists())
            self.assertTrue(any("Removed obsolete archive cache file" in line for line in logs))

    def test_archive_scan_cache_reuses_compact_entry_metadata_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            saved_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=saved_metadata)
            loaded_metadata: dict[str, object] = {}

            with mock.patch(
                "cdmw.core.archive._update_archive_entry_metadata_row_hash",
                side_effect=AssertionError("row hash should come from compact metadata"),
            ):
                loaded = load_archive_scan_cache(root, cache_root, metadata_out=loaded_metadata)

            self.assertIsNotNone(loaded)
            self.assertEqual(saved_metadata.get("entry_metadata_signature"), loaded_metadata.get("entry_metadata_signature"))
            self.assertEqual(saved_metadata.get("entry_metadata_sources"), loaded_metadata.get("entry_metadata_sources"))

    def test_legacy_monolithic_scan_cache_is_reported_migrated_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            legacy_cache_path = save_archive_scan_cache(root, cache_root, entries)

            health = archive_scan_shard_cache_health(root, cache_root)
            self.assertEqual("stale", health["status"])
            self.assertIn("older monolithic format", health["reason"])

            logs: list[str] = []
            loaded_entries, source, cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                shard_scan_func=lambda _path: (_ for _ in ()).throw(AssertionError("valid legacy cache should migrate without rescan")),
                on_log=logs.append,
            )

            self.assertEqual("cache", source)
            self.assertEqual([entry.path for entry in loaded_entries], ["character/model/a.pac"])
            self.assertTrue(cache_dir.is_dir())
            self.assertFalse(legacy_cache_path.exists())
            self.assertTrue(any("migrated to archive scan shard cache" in line for line in logs))

    def test_scan_shard_cache_rescans_only_changed_pamt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt_a, paz_a = _write_entry_files(root, "0000", data)
            pamt_b, paz_b = _write_entry_files(root, "0001", data)
            entries_by_pamt = {
                pamt_a: [_entry("character/model/a.pac", pamt_a, paz_a, data)],
                pamt_b: [_entry("character/model/b.pac", pamt_b, paz_b, data)],
            }

            def shard_scan(path: Path) -> list[ArchiveEntry]:
                return list(entries_by_pamt[path])

            first_entries, _source, cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                shard_scan_func=shard_scan,
            )
            self.assertEqual([entry.path for entry in first_entries], ["character/model/a.pac", "character/model/b.pac"])
            self.assertTrue(resolve_archive_scan_shard_cache_dir(root, cache_root).is_dir())
            self.assertEqual(cache_dir, resolve_archive_scan_shard_cache_dir(root, cache_root))

            calls: list[str] = []
            entries_by_pamt[pamt_b] = [_entry("character/model/b_changed.pac", pamt_b, paz_b, data)]
            pamt_b.write_bytes(b"pamt changed")

            def changed_shard_scan(path: Path) -> list[ArchiveEntry]:
                calls.append(path.relative_to(root).as_posix())
                if path == pamt_a:
                    raise AssertionError("unchanged shard should load from cache")
                return list(entries_by_pamt[path])

            logs: list[str] = []
            second_entries, source, _cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                shard_scan_func=changed_shard_scan,
                on_log=logs.append,
            )

            self.assertEqual(source, "cache+scan")
            self.assertEqual(calls, ["0001/0.pamt"])
            self.assertEqual([entry.path for entry in second_entries], ["character/model/a.pac", "character/model/b_changed.pac"])
            self.assertTrue(any("Archive cache shard stale: 0001/0.pamt source stamps changed" in line for line in logs))

    def test_scan_shard_cache_reuses_metadata_sidecar_on_warm_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            first_metadata: dict[str, object] = {}
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries, metadata_out=first_metadata)
            second_metadata: dict[str, object] = {}

            with mock.patch(
                "cdmw.core.archive_scan_cache._archive_entry_metadata_from_entries",
                side_effect=AssertionError("warm shard cache should use metadata sidecar"),
            ):
                second_entries, source, _cache_dir = load_or_update_archive_scan_shards(
                    root,
                    cache_root,
                    shard_scan_func=lambda _path: (_ for _ in ()).throw(AssertionError("warm cache should not rescan")),
                    metadata_out=second_metadata,
                )

            self.assertEqual("cache", source)
            self.assertEqual([entry.path for entry in second_entries], ["character/model/a.pac"])
            self.assertEqual(first_metadata.get("entry_metadata_signature"), second_metadata.get("entry_metadata_signature"))
            self.assertEqual(first_metadata.get("entry_metadata_sources"), second_metadata.get("entry_metadata_sources"))

    def test_scan_shard_cache_health_reports_missing_healthy_and_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"abc"
            pamt_path, paz_path = _write_entry_files(root, "0001", data)
            entries = [_entry("character/model/test.pac", pamt_path, paz_path, data)]

            missing = archive_scan_shard_cache_health(root, cache_root, deep=True)
            self.assertEqual("missing", missing["status"])
            self.assertEqual(1, missing["missing_count"])

            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries)
            healthy = archive_scan_shard_cache_health(root, cache_root, deep=True)
            self.assertEqual("healthy", healthy["status"])
            self.assertIn("Cache Status: Healthy", healthy["reason"])

            pamt_path.write_bytes(b"changed")
            stale = archive_scan_shard_cache_health(root, cache_root, deep=True)
            self.assertEqual("stale", stale["status"])
            self.assertGreaterEqual(stale["stale_count"], 1)
            self.assertIn("source size or timestamp changed", stale["reason"])

    def test_scan_shard_cache_uses_full_scan_when_many_shards_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            entries_by_pamt: dict[Path, list[ArchiveEntry]] = {}
            all_entries: list[ArchiveEntry] = []
            for index in range(10):
                group = f"{index:04d}"
                data = bytes([index + 1])
                pamt, paz = _write_entry_files(root, group, data)
                entry = _entry(f"character/model/{group}.pac", pamt, paz, data)
                entries_by_pamt[pamt] = [entry]
                all_entries.append(entry)

            load_or_update_archive_scan_shards(
                root,
                cache_root,
                full_scan_func=lambda: list(all_entries),
                shard_scan_func=lambda path: list(entries_by_pamt[path]),
            )
            for index, pamt in enumerate(sorted(entries_by_pamt, key=lambda path: str(path))[:9]):
                pamt.write_bytes(f"changed {index}".encode("ascii"))
            full_scan_calls = 0

            def full_scan() -> list[ArchiveEntry]:
                nonlocal full_scan_calls
                full_scan_calls += 1
                return list(all_entries)

            logs: list[str] = []
            entries, source, _cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                full_scan_func=full_scan,
                shard_scan_func=lambda _path: (_ for _ in ()).throw(AssertionError("should use full scan")),
                on_log=logs.append,
            )

            self.assertEqual(source, "native_scan")
            self.assertEqual(full_scan_calls, 1)
            self.assertEqual([entry.path for entry in entries], [entry.path for entry in all_entries])
            self.assertTrue(any("Many archive scan shards stale" in line for line in logs))

    def test_full_scan_shard_write_reports_cache_progress_after_scan_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            all_entries: list[ArchiveEntry] = []
            for index in range(10):
                group = f"{index:04d}"
                data = bytes([index + 1])
                pamt, paz = _write_entry_files(root, group, data)
                all_entries.append(_entry(f"character/model/{group}.pac", pamt, paz, data))
            progress: list[str] = []

            entries, _source, _cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                full_scan_func=lambda: list(all_entries),
                shard_scan_func=lambda _path: (_ for _ in ()).throw(AssertionError("cold many-shard path should use full scan")),
                on_progress=lambda _current, _total, detail: progress.append(detail),
            )

            self.assertEqual([entry.path for entry in entries], [entry.path for entry in all_entries])
            self.assertTrue(any("Preparing archive scan shard cache" in detail for detail in progress))
            self.assertTrue(any("Writing archive scan shard cache" in detail for detail in progress))

    def test_native_scan_loaded_progress_is_not_reported_as_complete(self) -> None:
        accelerator = (REPO_ROOT / "cdmw" / "core" / "archive_accelerator.py").read_text(encoding="utf-8")

        self.assertIn(
            'on_progress(0, 0, f"Native archive scan loaded {len(entries):,} entries; preparing shard cache...")',
            accelerator,
        )
        self.assertNotIn('on_progress(len(entries), max(len(entries), 1), f"Native archive scan loaded', accelerator)

    def test_basic_index_shards_merge_local_rows_after_earlier_shard_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt_a, paz_a = _write_entry_files(root, "0000", data)
            pamt_b, paz_b = _write_entry_files(root, "0001", data)
            entries_v1 = [
                _entry("character/model/a.pac", pamt_a, paz_a, data),
                _entry("character/model/b.pac", pamt_b, paz_b, data),
            ]
            load_or_update_archive_basic_index_shards(root, cache_root, entries_v1)
            entries_v2 = [
                _entry("character/model/a.pac", pamt_a, paz_a, data),
                _entry("character/model/a_extra.pac", pamt_a, paz_a, data),
                _entry("character/model/b.pac", pamt_b, paz_b, data),
            ]
            logs: list[str] = []

            payload = load_or_update_archive_basic_index_shards(root, cache_root, entries_v2, on_log=logs.append)

            self.assertIsNotNone(payload)
            self.assertIs((payload or {})["path_index"]["character/model/b.pac"][0], entries_v2[2])
            self.assertEqual((payload or {}).get("rebuilt_shards"), 1)
            self.assertTrue(resolve_archive_basic_index_shard_cache_dir(root, cache_root).is_dir())

    def test_basic_index_shard_clean_load_does_not_prune_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            load_or_update_archive_basic_index_shards(root, cache_root, entries)

            with mock.patch(
                "cdmw.core.archive_index_cache.prune_archive_cache_root",
                side_effect=AssertionError("clean basic index load must not prune"),
            ):
                payload = load_or_update_archive_basic_index_shards(root, cache_root, entries)

            self.assertTrue((payload or {}).get("cache_loaded"))
            self.assertEqual((payload or {}).get("rebuilt_shards"), 0)

    def test_basic_index_shard_rebuild_still_prunes_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries_v1 = [_entry("character/model/a.pac", pamt, paz, data)]
            load_or_update_archive_basic_index_shards(root, cache_root, entries_v1)
            entries_v2 = [
                _entry("character/model/a.pac", pamt, paz, data),
                _entry("character/model/b.pac", pamt, paz, data),
            ]

            with mock.patch(
                "cdmw.core.archive_index_cache.prune_archive_cache_root",
                return_value={"removed_files": 0, "removed_bytes": 0},
            ) as prune:
                payload = load_or_update_archive_basic_index_shards(root, cache_root, entries_v2)

            self.assertEqual((payload or {}).get("rebuilt_shards"), 1)
            prune.assert_called_once()

    def test_basic_index_shards_use_scan_shard_signatures_without_rehashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries, metadata_out=scan_metadata)
            load_or_update_archive_basic_index_shards(root, cache_root, entries)

            with mock.patch(
                "cdmw.core.archive_scan_cache._archive_scan_cache_payload_components",
                side_effect=AssertionError("scan shard signatures should be reused"),
            ):
                payload = load_or_update_archive_basic_index_shards(
                    root,
                    cache_root,
                    entries,
                    shard_entry_signatures=scan_metadata.get("scan_shard_entry_signatures") or {},
                    shard_entry_counts=scan_metadata.get("scan_shard_entry_counts") or {},
                )

            self.assertTrue((payload or {}).get("cache_loaded"))

    def test_basic_index_shards_fall_back_when_scan_shard_count_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries, metadata_out=scan_metadata)
            load_or_update_archive_basic_index_shards(root, cache_root, entries)

            with mock.patch(
                "cdmw.core.archive_scan_cache._archive_scan_cache_payload_components",
                wraps=archive_scan_cache._archive_scan_cache_payload_components,
            ) as payload_components:
                payload = load_or_update_archive_basic_index_shards(
                    root,
                    cache_root,
                    entries,
                    shard_entry_signatures=scan_metadata.get("scan_shard_entry_signatures") or {},
                    shard_entry_counts={"0000/0.pamt": 999},
                )

            self.assertTrue((payload or {}).get("cache_loaded"))
            self.assertGreaterEqual(payload_components.call_count, 1)

    def test_name_search_shards_use_scan_shard_signatures_without_rehashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries, metadata_out=scan_metadata)
            load_or_update_archive_name_search_shards(
                root,
                cache_root,
                entries,
                {},
                shard_entry_signatures=scan_metadata.get("scan_shard_entry_signatures") or {},
                shard_entry_counts=scan_metadata.get("scan_shard_entry_counts") or {},
            )

            with mock.patch(
                "cdmw.core.archive_scan_cache._archive_scan_cache_payload_components",
                side_effect=AssertionError("scan shard signatures should be reused"),
            ):
                loaded_index = load_or_update_archive_name_search_shards(
                    root,
                    cache_root,
                    entries,
                    {},
                    shard_entry_signatures=scan_metadata.get("scan_shard_entry_signatures") or {},
                    shard_entry_counts=scan_metadata.get("scan_shard_entry_counts") or {},
                )

            self.assertIsNotNone(loaded_index)

    def test_paz_only_change_reuses_scan_and_basic_shards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/texture/a.dds", pamt, paz, data)]
            load_or_update_archive_scan_shards(root, cache_root, shard_scan_func=lambda _path: entries)
            load_or_update_archive_basic_index_shards(root, cache_root, entries)
            paz.write_bytes(b"changed paz payload")

            loaded_entries, source, _cache_dir = load_or_update_archive_scan_shards(
                root,
                cache_root,
                shard_scan_func=lambda _path: (_ for _ in ()).throw(AssertionError("paz-only change should not rescan")),
            )
            basic_payload = load_or_update_archive_basic_index_shards(root, cache_root, loaded_entries)

            self.assertEqual(source, "cache")
            self.assertEqual([entry.path for entry in loaded_entries], ["character/texture/a.dds"])
            self.assertTrue((basic_payload or {}).get("cache_loaded"))

    def test_native_derived_index_job_is_wired_as_preferred_basic_index_path(self) -> None:
        accelerator = (REPO_ROOT / "cdmw" / "core" / "archive_accelerator.py").read_text(encoding="utf-8")
        native = (REPO_ROOT / "native" / "cdmw_archive_accelerator" / "src" / "main.cpp").read_text(encoding="utf-8")
        scan_worker = (REPO_ROOT / "cdmw" / "workers" / "archive_scan_workers.py").read_text(encoding="utf-8")

        self.assertIn("def build_archive_basic_indexes_accelerated", accelerator)
        self.assertIn('"derived-index-job"', accelerator)
        self.assertIn("build_archive_entry_path_index(entries)", accelerator)
        self.assertIn("build_archive_entry_basename_index(entries)", accelerator)
        self.assertIn("build_archive_entry_extension_index(entries)", accelerator)
        self.assertIn("build_archive_entry_role_index(entries)", accelerator)
        self.assertIn("run_derived_index_job", native)
        self.assertIn('path_rows', native)
        self.assertIn('basename_rows', native)
        self.assertIn('extension_rows', native)
        self.assertIn("build_archive_basic_indexes_accelerated(", scan_worker)

    def test_basename_index_orders_nested_real_paths_before_shortcut_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = b"payload"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [
                _entry("character/cd_phm_00_hel_00_0363.pac", pamt, paz, data),
                _entry(
                    "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac",
                    pamt,
                    paz,
                    data,
                ),
                _entry("character/model/cd_phm_00_hel_00_0363.pac", pamt, paz, data),
            ]

            index = build_archive_entry_basename_index(entries)
            matches = index["cd_phm_00_hel_00_0363.pac"]

        self.assertEqual(
            matches[0].path,
            "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac",
        )
        self.assertEqual(matches[-1].path, "character/cd_phm_00_hel_00_0363.pac")

    def test_sidecar_cache_exact_metadata_match_loads_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = _sidecar_text("character/texture/a.dds")
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/modelproperty/a.pami", pamt, paz, data)]
            save_archive_texture_sidecar_cache(
                root,
                cache_root,
                entries,
                path_rows={"character/texture/a.dds": (0,)},
            )

            logs: list[str] = []
            loaded = load_archive_texture_sidecar_cache_rows(root, cache_root, entries, on_log=logs.append)

            self.assertIsNotNone(loaded)
            path_rows, _basename_rows = loaded or ({}, {})
            self.assertEqual(path_rows.get("character/texture/a.dds"), (0,))
            self.assertFalse(any("out of date" in line.lower() for line in logs))

    def test_sidecar_cache_v10_payload_stores_only_sidecar_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            sidecar_data = _sidecar_text("character/texture/a.dds")
            model_data = b"model"
            pamt_a, paz_a = _write_entry_files(root, "0000", sidecar_data)
            pamt_b, paz_b = _write_entry_files(root, "0001", model_data)
            entries = [
                _entry("character/modelproperty/a.pami", pamt_a, paz_a, sidecar_data),
                _entry("character/model/a.pac", pamt_b, paz_b, model_data),
            ]
            cache_path = save_archive_texture_sidecar_cache(
                root,
                cache_root,
                entries,
                path_rows={"character/texture/a.dds": (0,)},
            )

            raw_payload = _deserialize_cache_payload_from_path(
                cache_path,
                magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
                invalid_message="Texture sidecar cache header is not recognized.",
            )

            self.assertEqual(raw_payload.get("version"), 10)
            self.assertNotIn("entry_signatures", raw_payload)
            self.assertEqual(len(raw_payload.get("sidecar_entry_signatures") or ()), 1)
            self.assertEqual((raw_payload.get("sidecar_entry_signatures") or [(-1,)])[0][0], 0)

    def test_sidecar_cache_v10_ignores_non_sidecar_entry_changes_for_incremental_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            sidecar_data = _sidecar_text("character/texture/a.dds")
            model_data = b"model"
            pamt_a, paz_a = _write_entry_files(root, "0000", sidecar_data)
            pamt_b, paz_b = _write_entry_files(root, "0001", model_data)
            entries = [
                _entry("character/modelproperty/a.pami", pamt_a, paz_a, sidecar_data),
                _entry("character/model/a.pac", pamt_b, paz_b, model_data),
            ]
            save_archive_texture_sidecar_cache(
                root,
                cache_root,
                entries,
                path_rows={"character/texture/a.dds": (0,)},
            )
            changed_model_data = b"model changed"
            paz_b.write_bytes(changed_model_data)
            entries[1].comp_size = len(changed_model_data)
            entries[1].orig_size = len(changed_model_data)

            logs: list[str] = []
            with mock.patch(
                "cdmw.core.archive_sidecar_cache._build_archive_texture_sidecar_path_rows_for_indices",
                side_effect=AssertionError("non-sidecar change must not rescan sidecars"),
            ):
                loaded = load_archive_texture_sidecar_cache_rows(root, cache_root, entries, on_log=logs.append)

            self.assertIsNotNone(loaded)
            path_rows, _basename_rows = loaded or ({}, {})
            self.assertEqual(path_rows.get("character/texture/a.dds"), (0,))
            self.assertTrue(any("remapped without rescanning" in line for line in logs))

    def test_sidecar_cache_stale_metadata_refreshes_when_payload_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = _sidecar_text("character/texture/a.dds")
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/modelproperty/a.pami", pamt, paz, data)]
            save_archive_texture_sidecar_cache(
                root,
                cache_root,
                entries,
                path_rows={"character/texture/a.dds": (0,)},
            )
            metadata_path = resolve_archive_sidecar_cache_path(root, cache_root).with_suffix(".meta.json")
            metadata = metadata_path.read_text(encoding="utf-8")
            metadata_path.write_text(metadata.replace('"entry_count":1', '"entry_count":0'), encoding="utf-8")

            logs: list[str] = []
            loaded = load_archive_texture_sidecar_cache_rows(root, cache_root, entries, on_log=logs.append)

            self.assertIsNotNone(loaded)
            self.assertTrue(any("metadata refreshed without rescanning" in line for line in logs))
            self.assertIn('"entry_count":1', metadata_path.read_text(encoding="utf-8"))

    def test_sidecar_cache_v9_rescans_only_changed_sidecar_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data_a = _sidecar_text("character/texture/a.dds")
            data_b = _sidecar_text("character/texture/b.dds")
            pamt_a, paz_a = _write_entry_files(root, "0000", data_a)
            pamt_b, paz_b = _write_entry_files(root, "0001", data_b)
            entries = [
                _entry("character/modelproperty/a.pami", pamt_a, paz_a, data_a),
                _entry("character/modelproperty/b.pami", pamt_b, paz_b, data_b),
            ]
            cache_root.mkdir(parents=True, exist_ok=True)
            _base, old_sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_sidecar_cache_path(root, cache_root),
                magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
                payload={
                    "version": 9,
                    "created_at": 1.0,
                    "sources": old_sources,
                    "entry_count": len(entries),
                    "entry_signature_format": _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
                    "entry_signatures": _build_archive_entry_cache_signatures(root, entries),
                    "path_rows": {
                        "character/texture/a.dds": (0,),
                        "character/texture/b.dds": (1,),
                    },
                    "basename_rows": {"a.dds": (0,), "b.dds": (1,)},
                },
            )

            data_c = _sidecar_text("character/texture/c.dds", extra="<Changed/>")
            paz_b.write_bytes(data_c)
            entries[1].comp_size = len(data_c)
            entries[1].orig_size = len(data_c)

            logs: list[str] = []
            loaded = load_archive_texture_sidecar_cache_rows(root, cache_root, entries, on_log=logs.append)

            self.assertIsNotNone(loaded)
            path_rows, _basename_rows = loaded or ({}, {})
            self.assertEqual(path_rows.get("character/texture/a.dds"), (0,))
            self.assertNotIn("character/texture/b.dds", path_rows)
            self.assertEqual(path_rows.get("character/texture/c.dds"), (1,))
            self.assertTrue(any("rescanning 1 sidecar entries" in line for line in logs))

    def test_sidecar_cache_v8_stale_payload_falls_back_to_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data_a = _sidecar_text("character/texture/a.dds")
            pamt, paz = _write_entry_files(root, "0000", data_a)
            entries = [_entry("character/modelproperty/a.pami", pamt, paz, data_a)]
            _base, old_sources = _collect_archive_scan_sources_from_entries(root, entries)
            payload = {
                "version": 8,
                "created_at": 1.0,
                "sources": old_sources,
                "entry_count": len(entries),
                "path_rows": {"character/texture/a.dds": (0,)},
                "basename_rows": {"a.dds": (0,)},
            }
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_sidecar_cache_path(root, cache_root),
                magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
                payload=payload,
            )
            data_b = _sidecar_text("character/texture/b.dds", extra="<Changed/>")
            paz.write_bytes(data_b)
            entries[0].comp_size = len(data_b)
            entries[0].orig_size = len(data_b)

            logs: list[str] = []
            loaded = load_archive_texture_sidecar_cache_rows(root, cache_root, entries, on_log=logs.append)

            self.assertIsNone(loaded)
            self.assertTrue(any("does not contain v9 entry signatures" in line for line in logs))

    def test_derived_index_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data_a = b"a"
            data_b = b"bb"
            pamt_a, paz_a = _write_entry_files(root, "0000", data_a)
            pamt_b, paz_b = _write_entry_files(root, "0001", data_b)
            entries = [
                _entry("character/model/a.pac", pamt_a, paz_a, data_a),
                _entry("character/texture/a.dds", pamt_b, paz_b, data_b),
            ]
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={"a": "test item"},
                item_display_names={"a": "Test Item"},
                item_exact_display_names={"a": "Test Item"},
                item_related_display_names={"b": "Related Item"},
                item_asset_catalog=[{"display_name": "Test Item", "scope_filter": "test item"}],
                path_index=build_archive_entry_path_index(entries),
                basename_index=build_archive_entry_basename_index(entries),
                extension_index=build_archive_entry_extension_index(entries),
            )

            loaded = load_archive_derived_index_cache(root, cache_root, entries)

            self.assertIsNotNone(loaded)
            payload = loaded or {}
            self.assertEqual(payload.get("item_search_aliases"), {"a": "test item"})
            self.assertEqual(payload.get("item_display_names"), {"a": "Test Item"})
            self.assertEqual(payload.get("item_exact_display_names"), {"a": "Test Item"})
            self.assertEqual(payload.get("item_related_display_names"), {"b": "Related Item"})
            self.assertEqual(payload.get("item_asset_catalog"), [{"display_name": "Test Item", "scope_filter": "test item"}])
            self.assertIn("table_catalog", payload)
            self.assertNotIn("path_index", payload)
            self.assertNotIn("basename_index", payload)
            self.assertNotIn("extension_index", payload)

    def test_derived_index_cache_does_not_persist_large_entry_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [
                _entry(f"character/model/{index:05d}.pac", pamt, paz, data)
                for index in range(5000)
            ]
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={"a": "test item"},
                item_display_names={"a": "Test Item"},
                item_exact_display_names={"a": "Test Item"},
                item_related_display_names={"b": "Related Item"},
                item_asset_catalog=[{"display_name": "Test Item", "scope_filter": "test item"}],
                path_index=build_archive_entry_path_index(entries),
                basename_index=build_archive_entry_basename_index(entries),
                extension_index=build_archive_entry_extension_index(entries),
            )

            raw_payload = _deserialize_archive_derived_index_cache_payload_from_path(
                resolve_archive_derived_index_cache_path(root, cache_root)
            )

            self.assertEqual(raw_payload.get("version"), 11)
            self.assertEqual(
                raw_payload.get("table_catalog"),
                table_catalog_cache_metadata(row_counts={"item_asset_catalog": 1}),
            )
            self.assertNotIn("path_rows", raw_payload)
            self.assertNotIn("basename_rows", raw_payload)
            self.assertNotIn("extension_rows", raw_payload)
            self.assertNotIn("entry_signatures", raw_payload)

    def test_basic_index_cache_round_trip_uses_compact_entry_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data_a = b"a"
            data_b = b"bb"
            pamt_a, paz_a = _write_entry_files(root, "0000", data_a)
            pamt_b, paz_b = _write_entry_files(root, "0001", data_b)
            entries = [
                _entry("character/model/a.pac", pamt_a, paz_a, data_a),
                _entry("character/texture/a.dds", pamt_b, paz_b, data_b),
            ]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            save_archive_basic_index_cache(
                root,
                cache_root,
                entries,
                path_index=build_archive_entry_path_index(entries),
                basename_index=build_archive_entry_basename_index(entries),
                extension_index=build_archive_entry_extension_index(entries),
                role_index=build_archive_entry_role_index(entries),
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            with mock.patch(
                "cdmw.core.archive._collect_archive_scan_sources_from_entries",
                side_effect=AssertionError("entry source walk should not run"),
            ):
                loaded = load_archive_basic_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    current_sources=scan_metadata.get("entry_metadata_sources") or (),
                )

            self.assertIsNotNone(loaded)
            payload = loaded or {}
            self.assertEqual(
                [entry.path for entry in payload["path_index"]["character/model/a.pac"]],
                ["character/model/a.pac"],
            )
            self.assertEqual(
                [entry.path for entry in payload["basename_index"]["a.dds"]],
                ["character/texture/a.dds"],
            )
            self.assertEqual(
                sorted(entry.path for entry in payload["extension_index"][".pac"]),
                ["character/model/a.pac"],
            )
            self.assertEqual(
                [entry.path for entry in payload["role_index"]["model"]],
                ["character/model/a.pac"],
            )
            self.assertEqual(
                [entry.path for entry in payload["role_index"]["texture"]],
                ["character/texture/a.dds"],
            )

    def test_basic_index_cache_rejects_stale_metadata_and_old_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            save_archive_basic_index_cache(
                root,
                cache_root,
                entries,
                path_index=build_archive_entry_path_index(entries),
                basename_index=build_archive_entry_basename_index(entries),
                extension_index=build_archive_entry_extension_index(entries),
                role_index=build_archive_entry_role_index(entries),
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            logs: list[str] = []
            self.assertIsNone(
                load_archive_basic_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature="f" * 64,
                    on_log=logs.append,
                )
            )
            self.assertTrue(any("compact entry metadata changed" in line for line in logs))

            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_basic_index_cache_path(root, cache_root),
                magic=_ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
                payload={
                    "version": 1,
                    "entry_count": len(entries),
                    "path_rows": [("character/model/a.pac", (0,))],
                },
            )
            logs.clear()
            self.assertIsNone(load_archive_basic_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("format changed" in line for line in logs))

    def test_missing_basic_index_cache_is_background_rebuild_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]

            self.assertIsNone(load_archive_basic_index_cache(root, cache_root, entries))
            self.assertFalse(resolve_archive_basic_index_cache_path(root, cache_root).exists())

    def test_derived_index_cache_uses_compact_entry_metadata_without_source_walk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={"a": "test item"},
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            with mock.patch(
                "cdmw.core.archive._collect_archive_scan_sources_from_entries",
                side_effect=AssertionError("entry source walk should not run"),
            ):
                loaded = load_archive_derived_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    current_sources=scan_metadata.get("entry_metadata_sources") or (),
                )

            self.assertIsNotNone(loaded)
            self.assertEqual((loaded or {}).get("item_search_aliases"), {"a": "test item"})

    def test_derived_index_cache_skips_dependency_walk_when_compact_metadata_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={"a": "test item"},
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            with mock.patch(
                "cdmw.core.archive.archive_item_index_dependency_signature",
                side_effect=AssertionError("dependency signature walk should not run"),
            ):
                loaded = load_archive_derived_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    current_sources=scan_metadata.get("entry_metadata_sources") or (),
                )

            self.assertIsNotNone(loaded)
            self.assertEqual((loaded or {}).get("item_search_aliases"), {"a": "test item"})

    def test_derived_index_cache_save_skips_dependency_walk_when_compact_metadata_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)

            with mock.patch(
                "cdmw.core.archive.archive_item_index_dependency_signature",
                side_effect=AssertionError("dependency signature walk should not run during save"),
            ):
                save_archive_derived_index_cache(
                    root,
                    cache_root,
                    entries,
                    item_search_aliases={"a": "test item"},
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
                )

            payload = _deserialize_archive_derived_index_cache_payload_from_path(
                resolve_archive_derived_index_cache_path(root, cache_root)
            )
            self.assertEqual("", payload.get("item_index_dependency_signature"))

    def test_derived_index_cache_can_defer_name_search_binary_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            name_index = build_archive_name_search_index(entries, item_search_aliases={"a": "test item"})
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                item_search_aliases={"a": "test item"},
                archive_name_search_index=name_index,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            with mock.patch(
                "cdmw.core.archive._load_native_name_search_index_binary",
                side_effect=AssertionError("name-search binary should load later"),
            ), mock.patch(
                "cdmw.core.archive._archive_entry_shard_groups",
                side_effect=AssertionError("name-search shard metadata should not be hashed for deferred load"),
            ):
                deferred = load_archive_derived_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    current_sources=scan_metadata.get("entry_metadata_sources") or (),
                    load_name_search_index=False,
                )

            self.assertIsNotNone(deferred)
            self.assertTrue((deferred or {}).get("name_search_index_deferred"))
            self.assertNotIn("name_search_index", deferred or {})

            loaded = load_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                current_sources=scan_metadata.get("entry_metadata_sources") or (),
            )
            self.assertIsNotNone((loaded or {}).get("name_search_index"))

    def test_derived_index_cache_v10_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )
            cache_path = resolve_archive_derived_index_cache_path(root, cache_root)
            payload = _deserialize_archive_derived_index_cache_payload_from_path(cache_path)
            payload["version"] = 10
            _write_raw_pickle_cache_payload_to_path(
                cache_path,
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload=payload,
            )

            loaded = load_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                current_sources=scan_metadata.get("entry_metadata_sources") or (),
            )

            self.assertIsNotNone(loaded)

    def test_name_search_shard_metadata_v1_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("object/tools/cd_t0000_lantern_ring_0001.prefab", pamt, paz, data)]
            name_index = build_archive_name_search_index(entries)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                archive_name_search_index=name_index,
            )
            shard_dir = resolve_archive_name_search_shard_cache_dir(root, cache_root)
            meta_path = next(shard_dir.glob("*.json"))
            meta = _read_archive_name_search_shard_meta(meta_path)
            meta["version"] = 1
            _write_archive_name_search_shard_meta(meta_path, meta)

            loaded_index = load_or_update_archive_name_search_shards(
                root,
                cache_root,
                entries,
                item_search_aliases=None,
            )

            self.assertIsNotNone(loaded_index)
            self.assertEqual(loaded_index.rows_for_token("lantern"), (0,))

    def test_corrupt_name_search_shard_binary_rebuilds_single_shard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("object/tools/cd_t0000_lantern_ring_0001.prefab", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            name_index = build_archive_name_search_index(entries)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                archive_name_search_index=name_index,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                entry_metadata_sources=scan_metadata.get("entry_metadata_sources") or (),
            )
            shard_dir = resolve_archive_name_search_shard_cache_dir(root, cache_root)
            shard_path = next(shard_dir.glob("*.bin"))
            shard_path.write_bytes(b"bad")
            logs: list[str] = []

            loaded = load_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                current_sources=scan_metadata.get("entry_metadata_sources") or (),
                on_log=logs.append,
            )
            loaded_index = (loaded or {}).get("name_search_index")

            self.assertIsNotNone(loaded_index)
            self.assertEqual(loaded_index.rows_for_token("lantern"), (0,))
            self.assertTrue(any("rebuilding" in line.lower() for line in logs))

    def test_atomic_name_search_binary_write_keeps_previous_file_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("object/tools/cd_t0000_lantern_ring_0001.prefab", pamt, paz, data)]
            index = build_archive_name_search_index(entries)
            binary_path = cache_root / "name.bin"
            binary_path.parent.mkdir(parents=True)
            binary_path.write_bytes(b"old-good")

            with mock.patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    _write_native_name_search_index_binary(binary_path, index, len(entries))

            self.assertEqual(binary_path.read_bytes(), b"old-good")

    def test_derived_index_cache_loads_name_search_rows_lazily(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("object/tools/cd_t0000_lantern_ring_0001.prefab", pamt, paz, data)]
            name_index = build_archive_name_search_index(entries)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                archive_name_search_index=name_index,
            )

            loaded = load_archive_derived_index_cache(root, cache_root, entries)
            loaded_index = (loaded or {}).get("name_search_index")

            self.assertIsNotNone(loaded_index)
            lazy_rows = getattr(loaded_index, "token_rows", None)
            self.assertEqual(getattr(lazy_rows, "decoded_token_count", -1), 0)
            self.assertEqual(loaded_index.rows_for_token("lantern"), (0,))
            self.assertGreaterEqual(getattr(lazy_rows, "decoded_token_count", 0), 1)

    def test_lazy_name_search_index_resaves_without_decoding_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            second_cache_root = root / "cache_copy"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("object/tools/cd_t0000_lantern_ring_0001.prefab", pamt, paz, data)]
            name_index = build_archive_name_search_index(entries)
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                archive_name_search_index=name_index,
            )
            loaded = load_archive_derived_index_cache(root, cache_root, entries)
            loaded_index = (loaded or {}).get("name_search_index")
            lazy_rows = getattr(loaded_index, "token_rows", None)
            source_shard_dir = resolve_archive_name_search_shard_cache_dir(root, cache_root)

            self.assertEqual(getattr(lazy_rows, "decoded_token_count", -1), 0)
            save_archive_derived_index_cache(
                root,
                second_cache_root,
                entries,
                archive_name_search_index=loaded_index,
            )

            copied_shard_dir = resolve_archive_name_search_shard_cache_dir(root, second_cache_root)
            self.assertEqual(getattr(lazy_rows, "decoded_token_count", -1), 0)
            source_bins = sorted(path.name for path in source_shard_dir.glob("*.bin"))
            copied_bins = sorted(path.name for path in copied_shard_dir.glob("*.bin"))
            self.assertEqual(copied_bins, source_bins)
            for name in source_bins:
                self.assertEqual((copied_shard_dir / name).read_bytes(), (source_shard_dir / name).read_bytes())

    def test_old_derived_index_cache_missing_compact_metadata_rebuilds_without_source_walk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            scan_metadata: dict[str, object] = {}
            save_archive_scan_cache(root, cache_root, entries, metadata_out=scan_metadata)
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 11,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {"a": "old"},
                    "table_catalog": table_catalog_cache_metadata(row_counts={"item_asset_catalog": 0}),
                },
            )
            logs: list[str] = []

            with mock.patch(
                "cdmw.core.archive._collect_archive_scan_sources_from_entries",
                side_effect=AssertionError("entry source walk should not run"),
            ):
                loaded = load_archive_derived_index_cache(
                    root,
                    cache_root,
                    entries,
                    entry_metadata_signature=str(scan_metadata.get("entry_metadata_signature") or ""),
                    current_sources=scan_metadata.get("entry_metadata_sources") or (),
                    on_log=logs.append,
                )

            self.assertIsNone(loaded)
            self.assertTrue(any("missing compact metadata" in line for line in logs))

    def test_derived_index_cache_v8_is_rejected_after_table_catalog_metadata_added(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 8,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {"a": "old"},
                    "item_asset_catalog": [{"display_name": "Old Row"}],
                },
            )

            logs: list[str] = []
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("rebuilding it now" in line for line in logs))

    def test_derived_index_cache_v5_is_rejected_after_item_catalog_category_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/lantern.pac", pamt, paz, data)]
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 5,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {},
                    "item_asset_catalog": [
                        {
                            "display_name": "Wooden Lantern",
                            "category": "Material",
                            "group": "Wood / Stone",
                        }
                    ],
                },
            )

            logs: list[str] = []
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("rebuilding it now" in line for line in logs))

    def test_derived_index_cache_v6_is_rejected_after_weapon_category_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/dagger_tipped_spear.pac", pamt, paz, data)]
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 6,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {},
                    "item_asset_catalog": [
                        {
                            "display_name": "Tommaso Guard's Dagger-Tipped Spear",
                            "category": "Weapon",
                            "group": "Dagger / Rapier",
                        }
                    ],
                },
            )

            logs: list[str] = []
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("rebuilding it now" in line for line in logs))

    def test_derived_index_cache_v7_is_rejected_after_horse_gear_category_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/horsearmor_royal_plate.pac", pamt, paz, data)]
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 7,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {},
                    "item_asset_catalog": [
                        {
                            "display_name": "Royal Plate Armor",
                            "category": "Armor",
                            "group": "Body",
                        }
                    ],
                },
            )

            logs: list[str] = []
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("rebuilding it now" in line for line in logs))

    def test_derived_index_cache_rejects_source_mismatch_and_invalid_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            save_archive_derived_index_cache(
                root,
                cache_root,
                entries,
                path_index=build_archive_entry_path_index(entries),
                basename_index=build_archive_entry_basename_index(entries),
                extension_index=build_archive_entry_extension_index(entries),
            )
            paz.write_bytes(b"changed")
            entries[0].comp_size = len(b"changed")
            entries[0].orig_size = len(b"changed")
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries))

            resolve_archive_derived_index_cache_path(root, cache_root).write_bytes(b"bad-cache")
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries))

    def test_derived_index_cache_v1_is_rejected_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            _base, sources = _collect_archive_scan_sources_from_entries(root, entries)
            _write_raw_pickle_cache_payload_to_path(
                resolve_archive_derived_index_cache_path(root, cache_root),
                magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
                payload={
                    "version": 1,
                    "created_at": 1.0,
                    "sources": sources,
                    "entry_count": len(entries),
                    "item_search_aliases": {"a": "old"},
                    "path_rows": {"character/model/a.pac": (0,)},
                },
            )

            logs: list[str] = []
            self.assertIsNone(load_archive_derived_index_cache(root, cache_root, entries, on_log=logs.append))
            self.assertTrue(any("rebuilding it now" in line for line in logs))

    def test_archive_scan_cache_status_does_not_report_ready_too_early(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            data = b"a"
            pamt, paz = _write_entry_files(root, "0000", data)
            entries = [_entry("character/model/a.pac", pamt, paz, data)]
            progress: list[str] = []

            save_archive_scan_cache(
                root,
                cache_root,
                entries,
                on_progress=lambda _current, _total, detail: progress.append(detail),
            )

            self.assertIn("Archive index cache written; preparing browser indexes...", progress)
            self.assertNotIn("Archive cache is ready.", progress)

    def test_invalidate_archive_browser_cache_removes_name_search_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "cache"
            cache_root.mkdir()
            name_index_path = resolve_archive_name_search_index_cache_path(root, cache_root)
            name_index_path.write_bytes(b"name-search")
            scan_shard_dir = resolve_archive_scan_shard_cache_dir(root, cache_root)
            basic_shard_dir = resolve_archive_basic_index_shard_cache_dir(root, cache_root)
            name_shard_dir = resolve_archive_name_search_shard_cache_dir(root, cache_root)
            for shard_dir in (scan_shard_dir, basic_shard_dir, name_shard_dir):
                shard_dir.mkdir(parents=True)
                (shard_dir / "deadbeef.bin").write_bytes(b"shard")

            deleted = invalidate_archive_browser_cache(root, cache_root)

            self.assertFalse(name_index_path.exists())
            self.assertFalse(scan_shard_dir.exists())
            self.assertFalse(basic_shard_dir.exists())
            self.assertFalse(name_shard_dir.exists())
            self.assertIn(name_index_path, deleted)
            self.assertIn(scan_shard_dir, deleted)
            self.assertIn(basic_shard_dir, deleted)
            self.assertIn(name_shard_dir, deleted)

    def test_prune_archive_cache_root_removes_oldest_top_level_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            cache_root.mkdir()
            old_scan = cache_root / "archive_scan_old.bin"
            new_name = cache_root / "archive_name_search_new.bin"
            foreign = cache_root / "other.bin"
            old_scan.write_bytes(b"a" * 700)
            new_name.write_bytes(b"b" * 700)
            foreign.write_bytes(b"c" * 2000)
            old_time = 100.0
            new_time = 200.0
            old_scan.touch()
            new_name.touch()
            import os

            os.utime(old_scan, (old_time, old_time))
            os.utime(new_name, (new_time, new_time))

            report = prune_archive_cache_root(cache_root, max_bytes=1000, target_bytes=700)

            self.assertEqual(report["removed_files"], 1)
            self.assertFalse(old_scan.exists())
            self.assertTrue(new_name.exists())
            self.assertTrue(foreign.exists())

    def test_prune_archive_cache_root_removes_oldest_shard_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            cache_root.mkdir()
            old_shards = cache_root / "archive_scan_shards_old"
            new_shards = cache_root / "archive_basic_index_shards_new"
            old_shards.mkdir()
            new_shards.mkdir()
            (old_shards / "a.bin").write_bytes(b"a" * 700)
            (new_shards / "b.bin").write_bytes(b"b" * 700)
            foreign_dir = cache_root / "archive_unknown_shards"
            foreign_dir.mkdir()
            (foreign_dir / "keep.bin").write_bytes(b"c" * 2000)
            import os

            os.utime(old_shards / "a.bin", (100.0, 100.0))
            os.utime(new_shards / "b.bin", (200.0, 200.0))

            report = prune_archive_cache_root(cache_root, max_bytes=1000, target_bytes=700)

            self.assertGreaterEqual(report["removed_files"], 1)
            self.assertFalse(old_shards.exists())
            self.assertTrue(new_shards.exists())
            self.assertTrue(foreign_dir.exists())

    def test_prune_archive_cache_root_skips_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            cache_root.mkdir()
            protected_shards = cache_root / "archive_name_search_shards_current"
            old_shards = cache_root / "archive_scan_shards_old"
            protected_shards.mkdir()
            old_shards.mkdir()
            (protected_shards / "a.bin").write_bytes(b"a" * 700)
            (old_shards / "b.bin").write_bytes(b"b" * 700)
            import os

            os.utime(protected_shards / "a.bin", (100.0, 100.0))
            os.utime(old_shards / "b.bin", (200.0, 200.0))

            report = prune_archive_cache_root(
                cache_root,
                max_bytes=1000,
                target_bytes=700,
                protected_paths=(protected_shards,),
            )

            self.assertGreaterEqual(report["removed_files"], 1)
            self.assertTrue(protected_shards.exists())
            self.assertFalse(old_shards.exists())


if __name__ == "__main__":
    unittest.main()
