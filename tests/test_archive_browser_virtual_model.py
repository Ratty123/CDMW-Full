from pathlib import Path
import os
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.models import ArchiveEntry, ArchivePerformanceSettings, clamp_archive_performance_settings
from cdmw.ui.archive_browser_model import ArchiveBrowserModel, ArchiveBrowserRowPayload, ArchiveBrowserTreeView
from PySide6.QtCore import Qt
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
    def test_flat_model_is_virtual_and_maps_selection_to_entry_index(self) -> None:
        entries = [_entry(f"ui/texture/file_{index}.dds", index) for index in range(10_000)]
        model = ArchiveBrowserModel(
            row_provider=lambda index, show_full_path: ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path if show_full_path else ""),
                tooltips=(entries[index].path,) * 9,
            )
        )
        model.set_archive_state(entries, mode="flat")
        self.assertEqual(model.rowCount(), 10_000)
        index = model.find_index_for_entry(9876)
        self.assertTrue(index.isValid())
        node = model.node_from_index(index)
        self.assertEqual(model.entry_indexes_for_node(node), (9876,))
        self.assertEqual(model.data(index), "row 9876")

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
                archive_view_backend="bad",
                ui_frame_budget_ms=99,
                archive_fetch_batch_size=99999,
                background_worker_limit=999,
                native_archive_acceleration=False,
            )
        )
        self.assertEqual(settings.resource_profile, "balanced_60fps")
        self.assertEqual(settings.archive_view_backend, "virtual_model")
        self.assertEqual(settings.ui_frame_budget_ms, 16)
        self.assertEqual(settings.archive_fetch_batch_size, 5000)
        self.assertEqual(settings.background_worker_limit, 16)
        self.assertFalse(settings.native_archive_acceleration)

    def test_virtual_tree_view_selection_compatibility_surface(self) -> None:
        entries = [_entry(f"ui/file_{index}.dds", index) for index in range(3)]
        view = ArchiveBrowserTreeView()
        view.set_archive_state(entries, mode="flat")
        item = view.topLevelItem(1)
        view.setCurrentItem(item)
        self.assertEqual(view.currentItem().data(0), "file")
        self.assertEqual(view.currentItem().data(0, Qt.UserRole + 1), 1)
        self.assertEqual(len(view.selectedItems()), 1)


class ArchiveBrowserVirtualModelSourceGuards(unittest.TestCase):
    def test_main_archive_view_uses_virtual_tree_view(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("self.archive_tree = ArchiveBrowserTreeView(", source)
        self.assertIn("self.archive_tree.set_archive_state(", source)
        self.assertIn("prepare_archive_browser_state_accelerated", source)
        model_source = Path("cdmw/ui/archive_browser_model.py").read_text(encoding="utf-8")
        self.assertIn("def invalidate_archive_rows", model_source)
        self.assertIn("def invalidate_rows", model_source)

    def test_initial_archive_refresh_defers_active_sort_until_after_first_paint(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("initial_sort_column = self.archive_tree_sort_column", source)
        self.assertIn("initial_worker_sort_column = -1 if initial_sort_deferred else initial_sort_column", source)
        self.assertIn("self.archive_initial_sort_apply_pending = initial_sort_deferred", source)
        self.assertIn("sort_column=initial_worker_sort_column", source)
        self.assertIn("def _apply_archive_initial_sort_after_first_paint", source)
        self.assertIn("column in {1, 2} and self.archive_enhanced_index_state != \"ready\"", source)

    def test_enhanced_index_completion_invalidates_name_columns_without_post_ready_filter_refresh(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        enhanced_start = source.index("        def _handle_archive_enhanced_index_complete")
        enhanced_end = source.index("        def _handle_archive_enhanced_index_error", enhanced_start)
        enhanced_body = source[enhanced_start:enhanced_end]
        self.assertIn("self._invalidate_archive_browser_name_columns()", enhanced_body)
        self.assertIn("self._schedule_archive_initial_sort_after_first_paint(150)", enhanced_body)
        self.assertNotIn("self.archive_enhanced_filter_refresh_pending = True", enhanced_body)
        self.assertNotIn("self._schedule_archive_pending_enhanced_filter_refresh(150)", enhanced_body)

    def test_scan_worker_builds_missing_enhanced_indexes_before_ready(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        scan_start = source.index("    class ArchiveScanWorker")
        scan_end = source.index("    class ArchiveDerivedIndexCacheWriteWorker", scan_start)
        scan_body = source[scan_start:scan_end]
        self.assertIn("Archive enhanced indexes are stale or missing; building before browser ready.", scan_body)
        self.assertIn("self._build_enhanced_archive_indexes_inline(entries)", scan_body)
        self.assertIn("save_archive_derived_index_cache(", scan_body)
        self.assertNotIn("Deferring enhanced archive indexes until after initial browser render", scan_body)

    def test_no_filter_flat_initial_state_reuses_raw_entries(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        scan_start = source.index("    class ArchiveScanWorker")
        scan_end = source.index("    class ArchiveDerivedIndexCacheWriteWorker", scan_start)
        scan_body = source[scan_start:scan_end]
        self.assertIn('"backend": "raw_flat"', scan_body)
        self.assertIn('"filtered_entries": entries', scan_body)
        self.assertIn('dds_count = len(extension_index.get(".dds", ()))', scan_body)
        self.assertIn("Archive Browser state mode: raw_flat", scan_body)

    def test_archive_activation_defers_structure_filter_build_off_ui_thread(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("class ArchiveStructureFilterWorker", source)
        self.assertIn("self.archive_structure_filter_state = \"idle\"", source)
        controls_start = source.index("        def _refresh_archive_browser_view_stage_controls")
        controls_end = source.index("        def _refresh_archive_browser_view_stage_populate", controls_start)
        controls_body = source[controls_start:controls_end]
        self.assertIn("self._rebuild_archive_structure_filter_controls(defer_missing_children=True)", controls_body)
        self.assertNotIn("build_archive_structure_children_map(self.archive_entries)", controls_body)
        structure_start = source.index("        def _rebuild_archive_structure_filter_controls")
        structure_end = source.index("        def _handle_archive_structure_combo_changed", structure_start)
        structure_body = source[structure_start:structure_end]
        self.assertIn("Folder filters warming...", structure_body)
        self.assertIn("self._start_archive_structure_filter_worker", source)

    def test_pending_enhanced_filter_refresh_waits_for_visible_ready_browser(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        refresh_start = source.index("        def _apply_pending_archive_enhanced_filter_refresh")
        refresh_end = source.index("        def _mark_archive_filters_dirty", refresh_start)
        refresh_body = source[refresh_start:refresh_end]
        self.assertIn("not self._is_tool_visible_or_current(self.archive_browser_tab)", refresh_body)
        self.assertIn("self.archive_browser_preload_state != \"ready\"", refresh_body)
        self.assertIn("not self.archive_browser_first_visible_paint_done", refresh_body)
        self.assertIn("cause=enhanced_filter_refresh | state=applied", refresh_body)

    def test_archive_preview_loading_state_is_debounced(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        render_start = source.index("        def _render_archive_preview(")
        flush_start = source.index("        def _flush_scheduled_archive_preview_request(")
        render_body = source[render_start:flush_start]
        flush_body = source[flush_start: source.index("        def _archive_native_prefetch_candidate_entries(")]
        self.assertIn("force: bool = False", render_body)
        self.assertIn("if not force and self._mesh_replacement_builder_active():", render_body)
        self.assertIn("self._defer_archive_preview_refresh_for_builder(entry)", render_body)
        self.assertIn("self.scheduled_archive_preview_request = (request_id, entry, include_loose_preview_assets, bool(force))", render_body)
        self.assertNotIn('self.archive_preview_info_edit.setPlainText("Preparing archive preview...")', render_body)
        self.assertIn("if not force and self._mesh_replacement_builder_active():", flush_body)
        self.assertIn("self._show_archive_preview_loading_state(entry)", flush_body)

    def test_archive_preview_refresh_replaces_dark_toolbar_and_bypasses_builder_pause(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('self.archive_model_preview_refresh_button = QPushButton("Refresh")', source)
        self.assertIn(
            'self.archive_model_preview_refresh_button.clicked.connect(self._force_refresh_current_model_preview_assets)',
            source,
        )
        self.assertIn("def _mesh_replacement_builder_active(self) -> bool:", source)
        self.assertIn("def _defer_archive_preview_refresh_for_builder", source)
        self.assertIn("def _resume_archive_preview_after_builder(self) -> None:", source)
        self.assertIn("def _force_refresh_current_model_preview_assets(self) -> None:", source)
        self.assertIn("self._refresh_current_model_preview_assets(force=True)", source)
        self.assertIn("Archive Preview auto-refresh paused while Mesh Replacement Builder is open", source)
        self.assertNotIn("archive_model_preview_darkmode_button", source)
        self.assertNotIn("Preview Window Darkmode", source)

    def test_settings_expose_performance_page_and_new_fields(self) -> None:
        source = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn('"Performance"', source)
        self.assertIn("archive_resource_profile_combo", source)
        self.assertIn("archive_native_acceleration_checkbox", source)
        self.assertIn("performance/archive_fetch_batch_size", source)
        self.assertNotIn('self.tabs.addTab(performance_tab, "Archive Performance")', dialog_source)


if __name__ == "__main__":
    unittest.main()
