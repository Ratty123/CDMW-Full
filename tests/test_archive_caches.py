from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from cdmw.core.archive import (
    _ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
    _ARCHIVE_SIDECAR_CACHE_MAGIC,
    _collect_archive_scan_sources_from_entries,
    _deserialize_archive_derived_index_cache_payload_from_path,
    _write_raw_pickle_cache_payload_to_path,
    build_archive_entry_basename_index,
    build_archive_entry_extension_index,
    build_archive_entry_path_index,
    load_archive_derived_index_cache,
    load_archive_texture_sidecar_cache_rows,
    invalidate_archive_browser_cache,
    prune_archive_cache_root,
    resolve_archive_name_search_index_cache_path,
    resolve_archive_derived_index_cache_path,
    resolve_archive_sidecar_cache_path,
    save_archive_derived_index_cache,
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

    def test_native_derived_index_job_is_wired_as_preferred_basic_index_path(self) -> None:
        accelerator = (REPO_ROOT / "cdmw" / "core" / "archive_accelerator.py").read_text(encoding="utf-8")
        native = (REPO_ROOT / "native" / "cdmw_archive_accelerator" / "src" / "main.cpp").read_text(encoding="utf-8")
        main_window = (REPO_ROOT / "cdmw" / "ui" / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("def build_archive_basic_indexes_accelerated", accelerator)
        self.assertIn('"derived-index-job"', accelerator)
        self.assertIn("build_archive_entry_path_index(entries)", accelerator)
        self.assertIn("build_archive_entry_basename_index(entries)", accelerator)
        self.assertIn("build_archive_entry_extension_index(entries)", accelerator)
        self.assertIn("run_derived_index_job", native)
        self.assertIn('path_rows', native)
        self.assertIn('basename_rows', native)
        self.assertIn('extension_rows', native)
        self.assertIn("build_archive_basic_indexes_accelerated(", main_window)

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
            save_archive_texture_sidecar_cache(
                root,
                cache_root,
                entries,
                path_rows={
                    "character/texture/a.dds": (0,),
                    "character/texture/b.dds": (1,),
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

            self.assertEqual(raw_payload.get("version"), 10)
            self.assertEqual(
                raw_payload.get("table_catalog"),
                table_catalog_cache_metadata(row_counts={"item_asset_catalog": 1}),
            )
            self.assertNotIn("path_rows", raw_payload)
            self.assertNotIn("basename_rows", raw_payload)
            self.assertNotIn("extension_rows", raw_payload)
            self.assertNotIn("entry_signatures", raw_payload)

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
            self.assertTrue(any("rebuilding lightweight cache" in line for line in logs))

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
            self.assertTrue(any("rebuilding lightweight cache" in line for line in logs))

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
            self.assertTrue(any("rebuilding lightweight cache" in line for line in logs))

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
            self.assertTrue(any("rebuilding lightweight cache" in line for line in logs))

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
            self.assertTrue(any("rebuilding lightweight cache" in line for line in logs))

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

            deleted = invalidate_archive_browser_cache(root, cache_root)

            self.assertFalse(name_index_path.exists())
            self.assertIn(name_index_path, deleted)

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


if __name__ == "__main__":
    unittest.main()
