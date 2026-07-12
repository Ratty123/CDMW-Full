from pathlib import Path
from collections.abc import Iterator, Mapping
import os
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.models import ArchiveEntry, ArchivePerformanceSettings, clamp_archive_performance_settings
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser_model import ArchiveBrowserModel, ArchiveBrowserRowPayload, ArchiveBrowserTreeView
from cdmw.ui.settings_tab import SettingsTab
from cdmw.workers.archive_filter_workers import ArchiveFilterWorker
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication


_APP = QApplication.instance() or QApplication([])


def _entry(path: str, index: int) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("pkg/test.pamt"),
        paz_file=Path("pkg/test.paz"),
        offset=index,
        comp_size=10,
        orig_size=20,
        flags=0,
        paz_index=0,
    )


class ArchiveBrowserVirtualModelTests(unittest.TestCase):
    def test_archive_mesh_swap_same_entry_uses_instance_helper(self) -> None:
        entry = _entry("character/model/body.pac", 1)
        self.assertTrue(ArchiveMeshSwapSupportMixin()._same_archive_entry(entry, entry))

    def test_archive_mesh_swap_identity_distinguishes_duplicate_paths_by_offset(self) -> None:
        first = _entry("character/model/body.pac", 1)
        second = _entry("character/model/body.pac", 2)

        self.assertFalse(ArchiveMeshSwapSupportMixin()._same_archive_entry(first, second))

    def test_archive_filter_worker_candidate_entries_intersect_basic_indexes(self) -> None:
        dds_texture = _entry("ui/texture/a.dds", 1)
        dds_mesh = _entry("ui/model/b.dds", 2)
        txt_texture = _entry("ui/texture/c.txt", 3)
        worker = ArchiveFilterWorker(
            [dds_texture, dds_mesh, txt_texture],
            entries_by_extension={".dds": [dds_texture, dds_mesh]},
            entries_by_role={"texture": [dds_texture, txt_texture]},
            extension_filter=".dds",
            role_filter="texture",
        )

        candidates, label = worker._candidate_entries_for_filter()

        self.assertEqual(list(candidates), [dds_texture])
        self.assertEqual(label, "extension:.dds+role:texture")

    def test_archive_filter_worker_retains_item_name_mappings_without_iterating(self) -> None:
        class NonIterableMapping(Mapping[str, str]):
            def __getitem__(self, key: str) -> str:
                return "value"

            def __iter__(self) -> Iterator[str]:
                raise AssertionError("mapping was copied on the caller thread")

            def __len__(self) -> int:
                return 1

        mapping = NonIterableMapping()

        worker = ArchiveFilterWorker(
            [],
            item_search_aliases=mapping,
            item_display_names=mapping,
            item_exact_display_names=mapping,
            item_related_display_names=mapping,
        )

        self.assertIs(worker.item_search_aliases, mapping)
        self.assertIs(worker.item_display_names, mapping)
        self.assertIs(worker.item_exact_display_names, mapping)
        self.assertIs(worker.item_related_display_names, mapping)

    def test_flat_model_is_virtual_and_maps_selection_to_entry_index(self) -> None:
        entries = [_entry(f"ui/texture/file_{index}.dds", index) for index in range(10_000)]
        model = ArchiveBrowserModel(
            row_provider=lambda index, show_full_path: ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path if show_full_path else ""),
                tooltips=(entries[index].path,) * 9,
            )
        )
        model.set_archive_state(entries, mode="flat", fetch_batch_size=500)
        self.assertEqual(model.rowCount(), 500)
        self.assertTrue(model.canFetchMore(model.index(-1, -1)))
        self.assertFalse(model.find_index_for_entry(9876).isValid())
        while model.canFetchMore(model.index(-1, -1)):
            model.fetchMore(model.index(-1, -1))
        self.assertEqual(model.rowCount(), 10_000)
        index = model.find_index_for_entry(9876)
        self.assertTrue(index.isValid())
        node = model.node_from_index(index)
        self.assertEqual(model.entry_indexes_for_node(node), (9876,))
        self.assertEqual(model.data(index), "row 9876")

    def test_flat_model_100k_traversal_keeps_only_bounded_row_payloads(self) -> None:
        entries = [_entry("ui/texture/shared.dds", 0)] * 100_000
        model = ArchiveBrowserModel(
            row_cache_limit=32,
            row_provider=lambda index, _show_full_path: ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "-", "Texture", "20 B", "None", "pkg", "-", "")
            ),
        )
        model.set_archive_state(entries, mode="flat", fetch_batch_size=5000)
        root = model.index(-1, -1)
        while model.canFetchMore(root):
            model.fetchMore(root)

        for row in range(100_000):
            index = model.index(row, 0)
            self.assertEqual(model.entry_indexes_for_node(model.node_from_index(index)), (row,))
            self.assertEqual(model.data(index, Qt.DisplayRole), f"row {row}")

        self.assertFalse(hasattr(model, "_flat_node_cache"))
        self.assertLessEqual(len(model._row_cache), 32)

    def test_folder_fetch_is_bounded_and_lazy(self) -> None:
        entries = [_entry(f"ui/texture/folder/file_{index}.dds", index) for index in range(250)]
        model = ArchiveBrowserModel()
        folder_key = ("ui",)
        model.set_archive_state(
            entries,
            mode="folders",
            tree_child_folders={(): [("ui", folder_key)]},
            tree_direct_files={folder_key: list(range(250))},
            tree_folder_entry_indexes={folder_key: list(range(250))},
            fetch_batch_size=100,
        )
        folder = model.index(0, 0)
        self.assertTrue(model.canFetchMore(folder))
        model.fetchMore(folder)
        self.assertEqual(model.rowCount(folder), 100)
        self.assertTrue(model.canFetchMore(folder))

    def test_display_role_does_not_compute_lazy_tooltips(self) -> None:
        entries = [_entry("ui/texture/file.dds", 0)]
        tooltip_calls = 0

        def row_provider(index: int, show_full_path: bool) -> ArchiveBrowserRowPayload:
            del show_full_path

            def tooltips() -> tuple[str, ...]:
                nonlocal tooltip_calls
                tooltip_calls += 1
                return (entries[index].path,) * 9

            return ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path),
                tooltip_provider=tooltips,
            )

        model = ArchiveBrowserModel(row_provider=row_provider)
        model.set_archive_state(entries, mode="flat")
        index = model.index(0, 0)
        self.assertEqual(model.data(index, Qt.DisplayRole), "row 0")
        self.assertEqual(tooltip_calls, 0)
        self.assertEqual(model.data(index, Qt.ToolTipRole), entries[0].path)
        self.assertEqual(tooltip_calls, 1)

    def test_row_cache_is_bounded_lru(self) -> None:
        entries = [_entry(f"ui/file_{index}.dds", index) for index in range(5)]
        model = ArchiveBrowserModel(
            row_cache_limit=2,
            row_provider=lambda index, _show_full_path: ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path),
            ),
        )
        model.set_archive_state(entries, mode="flat")
        for row in range(5):
            self.assertEqual(model.data(model.index(row, 0), Qt.DisplayRole), f"row {row}")
        self.assertLessEqual(len(model._row_cache), 2)
        self.assertNotIn((0, True), model._row_cache)
        self.assertIn((4, True), model._row_cache)

    def test_invalidate_rows_clears_cached_name_columns_and_repaints(self) -> None:
        entries = [_entry("character/model/test.pac", 0)]
        name_columns = {"exact": "-", "evidence": "-"}
        changed_ranges: list[tuple[int, int]] = []

        def row_provider(index: int, show_full_path: bool) -> ArchiveBrowserRowPayload:
            del index, show_full_path
            return ArchiveBrowserRowPayload(
                columns=(
                    "test.pac",
                    name_columns["exact"],
                    name_columns["evidence"],
                    "Model",
                    "20 B",
                    "None",
                    "pkg",
                    "-",
                    "character/model/test.pac",
                ),
            )

        model = ArchiveBrowserModel(row_provider=row_provider)
        model.dataChanged.connect(lambda top_left, bottom_right, _roles: changed_ranges.append((top_left.column(), bottom_right.column())))
        model.set_archive_state(entries, mode="flat")
        self.assertEqual(model.data(model.index(0, 1), Qt.DisplayRole), "-")

        name_columns["exact"] = "Sword of the Lord"
        name_columns["evidence"] = "Exact localization"
        model.invalidate_rows((1, 2))

        self.assertEqual(model.data(model.index(0, 1), Qt.DisplayRole), "Sword of the Lord")
        self.assertEqual(model.data(model.index(0, 2), Qt.DisplayRole), "Exact localization")
        self.assertIn((1, 2), changed_ranges)

    def test_folder_child_parent_lookup_uses_stable_row_numbers(self) -> None:
        entries = [_entry(f"ui/texture/folder/file_{index}.dds", index) for index in range(3)]
        model = ArchiveBrowserModel()
        folder_key = ("ui",)
        model.set_archive_state(
            entries,
            mode="folders",
            tree_child_folders={(): [("ui", folder_key)]},
            tree_direct_files={folder_key: list(range(3))},
            tree_folder_entry_indexes={folder_key: list(range(3))},
            fetch_batch_size=100,
        )
        folder = model.index(0, 0)
        model.fetchMore(folder)
        child = model.index(2, 0, folder)
        parent = model.parent(child)
        self.assertTrue(parent.isValid())
        self.assertEqual(parent.row(), 0)
        self.assertEqual(child.row(), 2)

    def test_performance_settings_clamp_new_resource_fields(self) -> None:
        settings = clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                resource_profile="bad",
                ui_frame_budget_ms=99,
                archive_fetch_batch_size=99999,
                background_worker_limit=999,
                native_archive_acceleration=False,
                native_preview_cache_mode="bad",
            )
        )
        self.assertEqual(settings.resource_profile, "balanced_60fps")
        self.assertEqual(settings.ui_frame_budget_ms, 16)
        self.assertEqual(settings.archive_fetch_batch_size, 5000)
        self.assertEqual(settings.background_worker_limit, 16)
        self.assertFalse(settings.native_archive_acceleration)
        self.assertEqual(settings.native_preview_cache_mode, "balanced")

    def test_virtual_tree_view_selection_compatibility_surface(self) -> None:
        entries = [_entry(f"ui/file_{index}.dds", index) for index in range(3)]
        view = ArchiveBrowserTreeView()
        view.set_archive_state(entries, mode="flat")
        item = view.topLevelItem(1)
        view.setCurrentItem(item)
        self.assertEqual(view.currentItem().data(0), "file")
        self.assertEqual(view.currentItem().data(0, Qt.UserRole + 1), 1)
        self.assertEqual(len(view.selectedItems()), 1)

    def test_hidden_columns_compact_after_visible_archive_columns(self) -> None:
        view = ArchiveBrowserTreeView()
        header = view.header()
        header.setSectionsMovable(True)
        header.moveSection(header.visualIndex(6), 1)
        header.moveSection(header.visualIndex(5), 3)
        view.setColumnHidden(5, True)
        view.setColumnHidden(6, True)

        view.compact_hidden_columns()

        visual_order = [header.logicalIndex(visual_index) for visual_index in range(header.count())]
        visible_order = [column for column in visual_order if not view.isColumnHidden(column)]
        hidden_order = [column for column in visual_order if view.isColumnHidden(column)]
        self.assertEqual([0, 1, 2, 3, 4, 7, 8], visible_order)
        self.assertEqual([6, 5], hidden_order)
        self.assertGreaterEqual(header.visualIndex(5), len(visible_order))
        self.assertGreaterEqual(header.visualIndex(6), len(visible_order))


class ArchivePerformanceSettingsTabTests(unittest.TestCase):
    def _settings_tab(self) -> SettingsTab:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        settings = QSettings(str(Path(temp_dir.name) / "settings.ini"), QSettings.IniFormat)
        tab = SettingsTab(settings=settings, theme_key="crimson_desert")
        self.addCleanup(tab.deleteLater)
        return tab

    def test_numeric_performance_presets_keep_auto_and_custom_values_clear(self) -> None:
        tab = self._settings_tab()
        tab.sync_archive_performance_controls(
            ArchivePerformanceSettings(archive_fetch_batch_size=0, preview_cache_limit=64)
        )
        self.assertEqual(0, tab.archive_fetch_batch_mode_combo.currentData())
        self.assertTrue(tab.archive_fetch_batch_spin.isHidden())
        self.assertEqual(64, tab.archive_preview_cache_limit_mode_combo.currentData())
        self.assertTrue(tab.archive_preview_cache_limit_spin.isHidden())

        batch_index = tab.archive_fetch_batch_mode_combo.findData(600)
        self.assertGreaterEqual(batch_index, 0)
        tab.archive_fetch_batch_mode_combo.setCurrentIndex(batch_index)
        self.assertEqual(600, tab.current_archive_performance_settings().archive_fetch_batch_size)

        custom_batch_index = tab.archive_fetch_batch_mode_combo.findData(-1)
        self.assertGreaterEqual(custom_batch_index, 0)
        tab.archive_fetch_batch_mode_combo.setCurrentIndex(custom_batch_index)
        tab.archive_fetch_batch_spin.setValue(2400)
        self.assertEqual(2400, tab.current_archive_performance_settings().archive_fetch_batch_size)

        tab.sync_archive_performance_controls(
            ArchivePerformanceSettings(archive_fetch_batch_size=2400, preview_cache_limit=96)
        )
        self.assertEqual(-1, tab.archive_fetch_batch_mode_combo.currentData())
        self.assertEqual(2400, tab.archive_fetch_batch_spin.value())
        self.assertEqual(-1, tab.archive_preview_cache_limit_mode_combo.currentData())
        self.assertEqual(96, tab.archive_preview_cache_limit_spin.value())


class ArchiveBrowserVirtualModelSourceGuards(unittest.TestCase):
    def test_main_archive_view_uses_virtual_tree_view(self) -> None:
        source = "\n".join(
            (
                Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/archive_browser/files_panel.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/archive_browser/controller.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/archive_browser/header.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/shell/responsiveness_controller.py").read_text(encoding="utf-8"),
            )
        )
        scan_worker = Path("cdmw/workers/archive_scan_workers.py").read_text(encoding="utf-8")
        self.assertIn("self.archive_tree = ArchiveBrowserTreeView(", source)
        self.assertIn("self.archive_tree.set_archive_state(", source)
        self.assertIn("self.archive_tree.compact_hidden_columns()", source)
        self.assertIn("def _schedule_archive_files_pane_fit_to_columns", source)
        self.assertIn("prepare_archive_browser_state_accelerated", scan_worker)
        model_source = Path("cdmw/ui/archive_browser/model.py").read_text(encoding="utf-8")
        self.assertIn("self._flat_loaded_count", model_source)
        self.assertIn("return self.createIndex(row, column)", model_source)
        self.assertNotIn("_flat_node_cache", model_source)
        self.assertIn("def compact_hidden_columns", model_source)
        self.assertIn("def invalidate_archive_rows", model_source)
        self.assertIn("def invalidate_rows", model_source)

    def test_initial_archive_refresh_defers_active_sort_until_after_first_paint(self) -> None:
        source = "\n".join(
            (
                Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/archive_browser/scan_lifecycle.py").read_text(encoding="utf-8"),
                Path("cdmw/ui/archive_browser/render_lifecycle.py").read_text(encoding="utf-8"),
            )
        )
        self.assertIn("initial_sort_column = self.archive_tree_sort_column", source)
        self.assertIn("initial_worker_sort_column = -1 if initial_sort_deferred else initial_sort_column", source)
        self.assertIn("self.archive_initial_sort_apply_pending = initial_sort_deferred", source)
        self.assertIn("sort_column=initial_worker_sort_column", source)
        self.assertIn("def _apply_archive_initial_sort_after_first_paint", source)
        self.assertIn("column in {1, 2} and self._archive_enhanced_index_missing_for_search()", source)

    def test_enhanced_index_completion_invalidates_name_columns_without_post_ready_filter_refresh(self) -> None:
        source = Path("cdmw/ui/archive_browser/index_workers.py").read_text(encoding="utf-8")
        enhanced_start = source.index("    def _handle_archive_enhanced_index_complete")
        enhanced_end = source.index("    def _handle_archive_enhanced_index_error", enhanced_start)
        enhanced_body = source[enhanced_start:enhanced_end]
        self.assertIn("self._invalidate_archive_browser_name_columns()", enhanced_body)
        self.assertIn("self._schedule_archive_initial_sort_after_first_paint(150)", enhanced_body)
        self.assertNotIn("self.archive_enhanced_filter_refresh_pending = True", enhanced_body)
        self.assertIn("if self.archive_enhanced_filter_refresh_pending:", enhanced_body)
        self.assertIn("self._schedule_archive_pending_enhanced_filter_refresh(150)", enhanced_body)
        self.assertIn("self._try_apply_startup_saved_filters()", enhanced_body)

    def test_scan_worker_builds_missing_rebuild_indexes_before_ready(self) -> None:
        scan_body = Path("cdmw/workers/archive_scan_workers.py").read_text(encoding="utf-8")
        run_start = scan_body.index("    @Slot()\n    def run")
        run_body = scan_body[run_start:]
        self.assertIn("Item-name search cache is missing or stale; archive list will open and search will build on demand.", run_body)
        self.assertIn("build_enhanced_indexes_before_ready = bool(", run_body)
        self.assertIn("or source != \"cache\"", run_body)
        self.assertIn("self._build_enhanced_archive_indexes_inline(", run_body)
        self.assertIn("shard_entry_signatures=scan_shard_entry_signatures", run_body)
        self.assertIn("shard_entry_counts=scan_shard_entry_counts", run_body)
        self.assertIn("Preparing archive search cache as part of archive cache build.", run_body)
        self.assertIn("Path lookup cache is deferred until filters", run_body)
        self.assertIn("load_or_update_archive_basic_index_shards(", run_body)
        self.assertIn("save_archive_basic_index_cache(", run_body)
        self.assertIn('"basic_index_needs_build": bool(', run_body)
        self.assertIn("role_index", run_body)
        self.assertIn('"enhanced_index_needs_build": enhanced_index_needs_build', run_body)
        self.assertIn("save_archive_derived_index_cache(", scan_body)

    def test_filter_worker_prefilters_candidates_from_basic_indexes(self) -> None:
        filter_body = Path("cdmw/workers/archive_filter_workers.py").read_text(encoding="utf-8")

        self.assertIn("entries_by_role", filter_body)
        self.assertIn("def _candidate_entries_for_filter", filter_body)
        self.assertIn("extension:{normalized_extension}", filter_body)
        self.assertIn("role:{normalized_role}", filter_body)
        self.assertIn("min(candidates, key=lambda item: len(item[1]))", filter_body)
        self.assertIn("Archive filter candidate set |", filter_body)
        self.assertIn("fallback_reason", filter_body)

    def test_no_filter_flat_initial_state_reuses_raw_entries(self) -> None:
        scan_body = Path("cdmw/workers/archive_scan_workers.py").read_text(encoding="utf-8")
        self.assertIn('"backend": "raw_flat"', scan_body)
        self.assertIn('"filtered_entries": entries', scan_body)
        self.assertIn('dds_count = int(extension_counts.get(".dds", 0) or 0)', scan_body)
        self.assertIn("Archive Browser state mode: raw_flat", scan_body)
        self.assertIn("Opening archive list from loaded entries...", scan_body)
        self.assertNotIn("Preparing first archive browser state from loaded entries...", scan_body)

    def test_archive_activation_defers_structure_filter_build_off_ui_thread(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/filter_workers.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/filter_controls.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/render_lifecycle.py").read_text(encoding="utf-8")
        )
        worker_source = Path("cdmw/workers/archive_workers.py").read_text(encoding="utf-8")
        self.assertIn("class ArchiveStructureFilterWorker", worker_source)
        self.assertIn("self.archive_structure_filter_state = \"idle\"", source)
        controls_start = source.index("    def _refresh_archive_browser_view_stage_controls")
        controls_end = source.index("    def _refresh_archive_browser_view_stage_populate", controls_start)
        controls_body = source[controls_start:controls_end]
        self.assertIn("self._rebuild_archive_structure_filter_controls(defer_missing_children=True)", controls_body)
        self.assertNotIn("build_archive_structure_children_map(self.archive_entries)", controls_body)
        structure_start = source.index("def _rebuild_archive_structure_filter_controls")
        structure_end = source.index("def _handle_archive_structure_combo_changed", structure_start)
        structure_body = source[structure_start:structure_end]
        self.assertIn("Folder filters warming...", structure_body)
        self.assertIn("self._start_archive_structure_filter_worker", source)

    def test_pending_enhanced_filter_refresh_waits_for_visible_browser_without_render_deadlock(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/filter_controls.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/render_lifecycle.py").read_text(encoding="utf-8")
        )
        refresh_start = source.index("    def _apply_pending_archive_enhanced_filter_refresh")
        refresh_end = source.index("    def _archive_browser_render_is_ready", refresh_start)
        refresh_body = source[refresh_start:refresh_end]
        self.assertIn("not self._is_tool_visible_or_current(self.archive_browser_tab)", refresh_body)
        self.assertNotIn("self.archive_browser_preload_state != \"ready\"", refresh_body)
        self.assertNotIn("not self.archive_browser_first_visible_paint_done", refresh_body)
        self.assertIn("cause=item_search_filter_refresh | state=applied", refresh_body)

    def test_archive_preview_loading_state_is_debounced(self) -> None:
        source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        render_start = source.index("    def _render_archive_preview(")
        flush_start = source.index("    def _flush_scheduled_archive_preview_request(")
        render_body = source[render_start:flush_start]
        flush_body = source[flush_start: source.index("    def _start_archive_preview_worker(")]
        self.assertIn("force: bool = False", render_body)
        self.assertIn("if not force and self._mesh_replacement_builder_active():", render_body)
        self.assertIn("self._defer_archive_preview_refresh_for_builder(entry)", render_body)
        self.assertIn("self.scheduled_archive_preview_request = (request_id, entry, include_loose_preview_assets, bool(force))", render_body)
        self.assertNotIn('self.archive_preview_info_edit.setPlainText("Preparing archive preview...")', render_body)
        self.assertIn("if not force and self._mesh_replacement_builder_active():", flush_body)
        self.assertIn("self._show_archive_preview_loading_state(entry)", flush_body)

    def test_native_core_preview_packages_are_not_cached_after_temp_cleanup(self) -> None:
        app_source = Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
        cache_source = Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8")
        result_source = Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8")
        worker_source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        source = app_source + "\n" + cache_source + "\n" + result_source + "\n" + worker_source
        cacheable_start = cache_source.index("    def _archive_preview_result_cacheable")
        cacheable_body = cache_source[cacheable_start: cache_source.index("    def _clone_archive_preview_result_for_cache", cacheable_start)]
        cached_start = cache_source.index("    def _get_cached_archive_preview_result")
        cached_body = cache_source[cached_start: cache_source.index("__all__", cached_start)]
        invalid_start = result_source.index('"d3d11_native_package_invalid_paths"')
        invalid_body = result_source[
            invalid_start: result_source.index("if self._archive_isolated_renderer_process_running()", invalid_start)
        ]
        flush_start = worker_source.index("    def _flush_scheduled_archive_preview_request(")
        flush_body = worker_source[flush_start: worker_source.index("    def _start_archive_preview_worker(", flush_start)]

        self.assertIn('native_package_path = str(getattr(result, "native_preview_package_path", "") or "").strip()', cacheable_body)
        self.assertIn("is_durable_native_preview_package_path", cacheable_body)
        self.assertIn("return bool(valid_package)", cacheable_body)
        self.assertIn('native_package_path = str(getattr(cached, "native_preview_package_path", "") or "").strip()', cached_body)
        self.assertIn("self.archive_preview_cache.pop(cache_key, None)", cached_body)
        self.assertIn('"archive_preview_cache_native_package_expired"', cached_body)
        self.assertIn('self.archive_preview_cache_last_miss_reason = "native_package_expired"', cached_body)
        self.assertIn("def _get_durable_native_preview_package_result", source)
        self.assertIn("lookup_native_preview_package_cache", source)
        self.assertIn("Cached preview package expired; rebuilding preview package...", flush_body)
        self.assertIn("Rebuilding native D3D11 preview package", flush_body)
        self.assertIn("self._stop_archive_preview_loading_indicator(success=False)", invalid_body)
        self.assertIn("self.archive_preview_info_edit.setPlainText(detail_text)", invalid_body)

    def test_archive_preview_refresh_replaces_dark_toolbar_and_bypasses_builder_pause(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_layout.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/signal_wiring.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/mesh_builder_lifecycle.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_panel.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8")
        )
        theme_source = Path("cdmw/ui/themes.py").read_text(encoding="utf-8")
        self.assertIn('self.archive_model_preview_refresh_button = QPushButton("Refresh")', source)
        self.assertIn("archive_model_preview_refresh_tooltip()", source)
        self.assertIn(
            'self.archive_model_preview_refresh_button.clicked.connect(self._force_refresh_current_model_preview_assets)',
            source,
        )
        self.assertIn("def _mesh_replacement_builder_active(self) -> bool:", source)
        self.assertIn("def _defer_archive_preview_refresh_for_builder", source)
        self.assertIn("def _resume_archive_preview_after_builder(self) -> None:", source)
        self.assertIn("def _force_refresh_current_model_preview_assets(self) -> None:", source)
        self.assertIn("self._refresh_current_model_preview_assets(force=True)", source)
        self.assertIn("alignment_builder_archive_preview_pause_message()", source)
        self.assertIn('self.archive_preview_health_label.setObjectName("ArchivePreviewHealthLabel")', source)
        self.assertIn("def _set_archive_preview_health_message(", source)
        self.assertIn('label.setProperty("attention", bool(attention))', source)
        self.assertIn("label.style().unpolish(label)", source)
        self.assertIn("label.style().polish(label)", source)
        self.assertIn("self._set_archive_preview_health_message(message, visible=bool(entry), attention=True)", source)
        self.assertIn("QLabel#ArchivePreviewHealthLabel {", theme_source)
        self.assertIn('QLabel#ArchivePreviewHealthLabel[attention="true"]', theme_source)
        self.assertNotIn("archive_model_preview_darkmode_button", source)
        self.assertNotIn("Preview Window Darkmode", source)

    def test_mesh_editor_strips_duplicate_d3d11_preview_payloads(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/mesh_editor/shell_bridge.py").read_text(encoding="utf-8")
        )
        cache_source = Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8")
        memory_source = Path("cdmw/ui/archive_browser/preview_memory.py").read_text(encoding="utf-8")
        strip_start = cache_source.index("    def _strip_archive_preview_heavy_payloads_for_mesh_editor")
        strip_body = cache_source[strip_start: cache_source.index("    def _trim_archive_preview_cache", strip_start)]
        memory_start = memory_source.index("    def _archive_memory_audit_payload")
        memory_body = memory_source[memory_start: memory_source.index("    def _record_archive_memory_audit", memory_start)]

        self.assertIn("archive_preview_cache_prepared_bytes", memory_body)
        self.assertIn("archive_preview_current_prepared_bytes", memory_body)
        self.assertIn("memory_total_private_bytes", memory_body)
        self.assertIn("self._clone_archive_preview_result_for_cache(", strip_body)
        self.assertIn("keep_prepared_model=False", strip_body)
        self.assertIn("same_current_entry", strip_body)
        self.assertIn("self._same_archive_entry(current_entry, entry)", strip_body)
        self.assertIn("self._shutdown_archive_isolated_renderer_host()", strip_body)
        self.assertIn('"mesh_editor_archive_preview_payloads_stripped"', strip_body)
        self.assertIn("reclaimed_prepared_bytes", strip_body)
        self.assertIn("self._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)", source)

    def test_settings_expose_performance_page_and_new_fields(self) -> None:
        source = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn('"Performance"', source)
        self.assertIn('workload_group, workload_layout = _performance_group("Overall Workload")', source)
        self.assertIn('archive_list_group, archive_list_layout = _performance_group("Archive List Loading")', source)
        self.assertIn('related_index_group, related_index_layout = _performance_group("Related-File Indexing")', source)
        self.assertIn('preview_cache_group, preview_cache_layout = _performance_group("Preview Caches")', source)
        self.assertIn("def _add_performance_row(", source)
        self.assertIn("SettingsPerformanceOverview", source)
        self.assertIn("SettingsPerformanceField", source)
        self.assertIn("SettingsPerformanceNote", source)
        self.assertIn("note.setMinimumWidth(260)", source)
        self.assertIn("note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)", source)
        self.assertNotIn("wrapped_height = note.fontMetrics().boundingRect", source)
        self.assertNotIn("note.setMaximumWidth(430)", source)
        self.assertIn("group.setMinimumWidth(520)", source)
        self.assertIn("group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)", source)
        self.assertNotIn("group.setMaximumWidth(600)", source)
        self.assertIn("grid.setColumnStretch(1, 1)", source)
        self.assertIn("performance_overview.setMinimumWidth(720)", source)
        self.assertIn("performance_overview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)", source)
        self.assertIn("performance_grid_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)", source)
        self.assertNotIn("performance_grid_widget.setMaximumWidth(1212)", source)
        self.assertIn("field_layout.addWidget(control, alignment=Qt.AlignLeft | Qt.AlignTop)", source)
        self.assertIn("field_layout.addWidget(note_widget)", source)
        self.assertIn("grid.addWidget(field_body, row, 1)", source)
        self.assertIn("grid.setRowMinimumHeight(row, 72)", source)
        self.assertIn("performance_columns = QHBoxLayout(performance_grid_widget)", source)
        self.assertIn("left_performance_column = QVBoxLayout()", source)
        self.assertIn("right_performance_column = QVBoxLayout()", source)
        self.assertIn("left_performance_column.setAlignment(Qt.AlignTop)", source)
        self.assertIn("right_performance_column.setAlignment(Qt.AlignTop)", source)
        self.assertIn("performance_columns.addLayout(left_performance_column, 1)", source)
        self.assertIn("performance_columns.addLayout(right_performance_column, 1)", source)
        self.assertIn("left_performance_column.addWidget(workload_group)", source)
        self.assertIn("right_performance_column.addWidget(archive_list_group)", source)
        self.assertIn("left_performance_column.addWidget(related_index_group)", source)
        self.assertIn("right_performance_column.addWidget(preview_cache_group)", source)
        self.assertIn("Recommended start: Balanced preset", source)
        self.assertIn("Balanced (recommended)", source)
        self.assertIn("Faster indexing (more CPU / possible lag)", source)
        self.assertIn("Low impact (slower / smoother)", source)
        self.assertIn("Native helper", source)
        self.assertIn("Rows per update", source)
        self.assertIn("archive_fetch_batch_mode_combo", source)
        self.assertIn("Auto (preset)", source)
        self.assertIn("100 rows (smooth)", source)
        self.assertIn("Custom...", source)
        self.assertIn("Sidecar index", source)
        self.assertIn('self.archive_sidecar_worker_mode_combo.addItem("Auto from preset (recommended)", 0)', source)
        self.assertIn("self.archive_sidecar_worker_mode_combo.setMinimumContentsLength(28)", source)
        self.assertIn("self.archive_sidecar_worker_mode_combo.setMinimumWidth(360)", source)
        self.assertIn("self.archive_sidecar_worker_mode_combo.setMaximumWidth(420)", source)
        self.assertIn("self.archive_sidecar_worker_spin.setVisible(manual)", source)
        self.assertIn("Cache warmup", source)
        self.assertIn("archive_preview_cache_limit_mode_combo", source)
        self.assertIn("Balanced 64 (recommended)", source)
        self.assertIn("High 128 (faster)", source)
        self.assertIn("D3D11 disk cache", source)
        self.assertIn("archive_resource_profile_combo", source)
        self.assertIn("archive_native_acceleration_checkbox", source)
        self.assertIn("archive_native_preview_cache_mode_combo", source)
        self.assertIn("self.archive_native_preview_cache_mode_combo.setMinimumWidth(360)", source)
        self.assertIn("archive/native_preview_cache_mode", source)
        self.assertIn("performance/archive_fetch_batch_size", source)
        self.assertNotIn("archive_view_backend_combo", source)
        self.assertNotIn("archive_ui_frame_budget_spin", source)
        self.assertNotIn("archive_background_worker_limit_spin", source)
        self.assertNotIn('self.tabs.addTab(performance_tab, "Performance")', dialog_source)
        self.assertNotIn('self.tabs.addTab(performance_tab, "Archive Performance")', dialog_source)

    def test_disabling_sidecar_index_cancels_active_and_pending_work(self) -> None:
        source = Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8")
        worker_source = Path("cdmw/workers/archive_sidecar_workers.py").read_text(encoding="utf-8")
        handler_start = source.index("    def _handle_archive_performance_settings_changed")
        handler_end = len(source)
        handler_source = source[handler_start:handler_end]

        self.assertIn("sidecar_indexing_work_active = bool(", handler_source)
        self.assertIn("self.archive_sidecar_thread is not None", handler_source)
        self.assertIn("self.archive_sidecar_pending_start", handler_source)
        self.assertIn("not performance_settings.enable_sidecar_indexing", handler_source)
        self.assertIn("self.archive_sidecar_request_id += 1", handler_source)
        self.assertIn("self.archive_sidecar_pending_start = False", handler_source)
        self.assertIn("self.archive_browser_warmup_pending = False", handler_source)
        self.assertIn("self.archive_sidecar_worker.stop()", handler_source)
        self.assertIn(
            'self._finish_archive_sidecar_status("Texture sidecar indexing stopped.", success=False)',
            handler_source,
        )
        self.assertIn("if self.stop_event.is_set():\n                    return", worker_source)
        self.assertIn("if not self.stop_event.is_set():\n                    self.completed.emit", worker_source)
        self.assertIn("self.progress_changed.emit(self.request_id, 1, 1, \"Texture sidecar cache is ready.\")", worker_source)


if __name__ == "__main__":
    unittest.main()
