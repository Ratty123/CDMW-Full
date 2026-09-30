from collections import OrderedDict
from collections.abc import Iterator, Mapping
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.models import ArchiveEntry, ArchivePerformanceSettings, clamp_archive_performance_settings
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin
from cdmw.ui.archive_browser_model import ArchiveBrowserModel, ArchiveBrowserRowPayload, ArchiveBrowserTreeView
from cdmw.ui.settings_tab import SettingsTab
from cdmw.ui.wrapping_layout import WrappingLayout
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QGroupBox, QLabel, QWidget


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



    def test_flat_model_is_virtual_and_maps_selection_to_entry_index(self) -> None:
        entries = [_entry(f"ui/texture/file_{index}.dds", index) for index in range(10_000)]
        model = ArchiveBrowserModel(
            row_provider=lambda index, show_full_path: ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path if show_full_path else ""),
                tooltips=(entries[index].path,) * 8,
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
                columns=(f"row {index}", "-", "Texture", "20 B", "None", "pkg", "-", "")
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
                return (entries[index].path,) * 8

            return ArchiveBrowserRowPayload(
                columns=(f"row {index}", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path),
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
                columns=(f"row {index}", "-", "Texture", "20 B", "None", "pkg", "-", entries[index].path),
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
        item_name = {"value": "-"}
        changed_ranges: list[tuple[int, int]] = []

        def row_provider(index: int, show_full_path: bool) -> ArchiveBrowserRowPayload:
            del index, show_full_path
            return ArchiveBrowserRowPayload(
                columns=(
                    "test.pac",
                    item_name["value"],
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

        item_name["value"] = "Sword of the Lord"
        model.invalidate_rows((1,))

        self.assertEqual(model.data(model.index(0, 1), Qt.DisplayRole), "Sword of the Lord")
        self.assertIn((1, 1), changed_ranges)

    def test_legacy_row_payload_merges_item_name_and_preserves_confidence_tooltip(self) -> None:
        entry = _entry("character/model/test.pac", 0)

        class Harness(ArchiveBrowserRowPayloadMixin):
            def __init__(self, name_match: tuple[str, str, str]) -> None:
                self.archive_filtered_entries = [entry]
                self.archive_entries_by_normalized_path = {entry.path.casefold(): [entry]}
                self.archive_browser_row_display_cache = OrderedDict()
                self.archive_browser_row_display_cache_limit = 4
                self.name_match = name_match

            def _archive_entry_item_name_match(self, _entry: ArchiveEntry) -> tuple[str, str, str]:
                return self.name_match

        exact = Harness(("Exact Blade", "", ""))._archive_browser_row_payload(0)
        inferred = Harness(("", "Related Blade", "Possible related item name; not proof."))._archive_browser_row_payload(0)

        self.assertEqual(len(exact.columns), 8)
        self.assertEqual(exact.columns[1], "Exact Blade")
        self.assertIn("Exact:", exact.tooltip(1))
        self.assertEqual(inferred.columns[1], "Related Blade")
        self.assertIn("not proof", inferred.tooltip(1))

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
                archive_fetch_batch_size=99999,
                native_archive_acceleration=False,
                native_preview_cache_mode="bad",
            )
        )
        self.assertEqual(settings.resource_profile, "balanced_60fps")
        self.assertEqual(settings.archive_fetch_batch_size, 5000)
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
        self.assertEqual([0, 1, 2, 3, 4, 7], visible_order)
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

    def test_performance_page_uses_aligned_card_grid(self) -> None:
        tab = self._settings_tab()
        tab.resize(1600, 900)
        tab.show_settings_section("performance")
        tab.show()
        _APP.processEvents()
        self.addCleanup(tab.hide)

        host = tab.findChild(QWidget, "SettingsPerformanceHost")
        content = tab.findChild(QWidget, "SettingsPerformanceContent")
        grid_widget = tab.findChild(QWidget, "SettingsPerformanceGrid")
        self.assertIsNotNone(host)
        self.assertIsNotNone(content)
        self.assertIsNotNone(grid_widget)
        assert host is not None
        assert content is not None
        assert grid_widget is not None
        self.assertEqual(1480, content.maximumWidth())
        self.assertGreater(content.width(), 1200)
        self.assertLessEqual(content.width(), host.width())

        grid = grid_widget.layout()
        self.assertIsInstance(grid, WrappingLayout)
        cards = {
            card.title(): card
            for card in grid_widget.findChildren(
                QGroupBox,
                "SettingsPerformanceCard",
                Qt.FindDirectChildrenOnly,
            )
        }
        self.assertEqual({"Overall Workload", "Archive List Loading", "Related-File Indexing", "Preview Caches"}, set(cards))
        self.assertEqual(cards["Overall Workload"].y(), cards["Archive List Loading"].y())
        self.assertEqual(cards["Related-File Indexing"].y(), cards["Preview Caches"].y())
        self.assertGreater(cards["Archive List Loading"].x(), cards["Overall Workload"].x())
        self.assertGreater(cards["Related-File Indexing"].y(), cards["Overall Workload"].y())
        self.assertLess(cards["Preview Caches"].geometry().bottom(), grid_widget.height())

        rows = grid_widget.findChildren(QFrame, "SettingsPerformanceRow")
        self.assertEqual(9, len(rows))
        self.assertEqual(4, sum(bool(row.property("firstRow")) for row in rows))
        for row in rows:
            row_layout = row.layout()
            self.assertIsInstance(row_layout, QGridLayout)
            assert isinstance(row_layout, QGridLayout)
            field = row.findChild(QLabel, "SettingsPerformanceField", Qt.FindDirectChildrenOnly)
            note = row.findChild(QLabel, "SettingsPerformanceNote", Qt.FindDirectChildrenOnly)
            self.assertIsNotNone(field)
            self.assertIsNotNone(note)
            assert field is not None
            assert note is not None
            self.assertEqual((0, 0, 1, 1), row_layout.getItemPosition(row_layout.indexOf(field)))
            self.assertEqual((2, 0, 1, 1), row_layout.getItemPosition(row_layout.indexOf(note)))

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
        self.assertIn("self.archive_tree = ArchiveBrowserTreeView(", source)
        self.assertIn("self.archive_tree.use_remote_model(", source)
        self.assertIn("self.archive_tree.compact_hidden_columns()", source)
        self.assertIn("def _schedule_archive_files_pane_fit_to_columns", source)
        model_source = Path("cdmw/ui/archive_browser/model.py").read_text(encoding="utf-8")
        self.assertIn("self._flat_loaded_count", model_source)
        self.assertIn("return self.createIndex(row, column)", model_source)
        self.assertNotIn("_flat_node_cache", model_source)
        self.assertIn("def compact_hidden_columns", model_source)
        self.assertIn("def invalidate_archive_rows", model_source)
        self.assertIn("def invalidate_rows", model_source)






    def test_structure_filters_use_the_resident_backend(self) -> None:
        source = Path("cdmw/ui/archive_browser/filter_workers.py").read_text(encoding="utf-8")
        self.assertIn("bridge.request_structure_children(", source)
        self.assertNotIn("build_archive_structure_children_map", source)
        self.assertNotIn("QThread", source)


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

    def test_dotnet_preview_packages_are_validated_before_cache_reuse(self) -> None:
        app_source = Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
        cache_source = Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8")
        result_source = Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8")
        worker_source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        source = app_source + "\n" + cache_source + "\n" + result_source + "\n" + worker_source
        cacheable_start = cache_source.index("    def _archive_preview_result_cacheable")
        cacheable_body = cache_source[cacheable_start: cache_source.index("    def _clone_archive_preview_result_for_cache", cacheable_start)]
        cached_start = cache_source.index("    def _get_cached_archive_preview_result")
        cached_body = cache_source[cached_start: cache_source.index("__all__", cached_start)]
        invalid_start = result_source.index('"dotnet_preview_package_invalid"')
        invalid_body = result_source[
            invalid_start: result_source.index("same_model = package_dir", invalid_start)
        ]
        flush_start = worker_source.index("    def _flush_scheduled_archive_preview_request(")
        flush_body = worker_source[flush_start: worker_source.index("    def _start_archive_preview_worker(", flush_start)]

        self.assertIn('dotnet_package_path = str(getattr(result, "dotnet_preview_package_path", "") or "").strip()', cacheable_body)
        self.assertIn("is_durable_dotnet_preview_package_path", cacheable_body)
        self.assertIn("validate_dotnet_preview_package", cacheable_body)
        self.assertIn("return bool(valid_package)", cacheable_body)
        self.assertIn('dotnet_package_path = str(getattr(cached, "dotnet_preview_package_path", "") or "").strip()', cached_body)
        self.assertIn("self.archive_preview_cache.pop(cache_key, None)", cached_body)
        self.assertIn('"archive_preview_cache_dotnet_package_expired"', cached_body)
        self.assertIn('self.archive_preview_cache_last_miss_reason = "dotnet_package_expired"', cached_body)
        self.assertNotIn("def _get_durable_native_preview_package_result", source)
        self.assertIn("Cached preview package expired; rebuilding preview package...", flush_body)
        self.assertIn('Rebuilding Preview package', flush_body)
        self.assertIn('Preview package validation failed', invalid_body)
        self.assertIn("self._set_archive_preview_base_detail_text", invalid_body)
        self.assertIn("self.shell.set_status_message(message, error=True)", invalid_body)
        self.assertIn("self.archive_d3d11_preview_host.load_package(", result_source)

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
            'self.archive.archive_model_preview_refresh_button.clicked.connect(self.archive._force_refresh_current_model_preview_assets)',
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
        self.assertIn('label.setProperty("working", bool(working))', source)
        self.assertIn("label.style().unpolish(label)", source)
        self.assertIn("label.style().polish(label)", source)
        self.assertIn("self._set_archive_preview_health_message(message, visible=bool(entry), attention=True)", source)
        self.assertIn("QLabel#ArchivePreviewHealthLabel {", theme_source)
        self.assertIn('QLabel#ArchivePreviewHealthLabel[working="true"]', theme_source)
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
        self.assertIn('self.archive._strip_archive_preview_heavy_payloads_for_mesh_editor(entry)', source)

    def test_settings_expose_performance_page_and_new_fields(self) -> None:
        source = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")
        theme_source = Path("cdmw/ui/themes.py").read_text(encoding="utf-8")
        self.assertIn('"Performance"', source)
        self.assertIn('workload_group, workload_layout = _performance_group("Overall Workload")', source)
        self.assertIn('archive_list_group, archive_list_layout = _performance_group("Archive List Loading")', source)
        self.assertIn('related_index_group, related_index_layout = _performance_group("Related-File Indexing")', source)
        self.assertIn('preview_cache_group, preview_cache_layout = _performance_group("Preview Caches")', source)
        self.assertIn("def _add_performance_row(", source)
        self.assertIn("SettingsPerformanceOverview", source)
        self.assertIn("SettingsPerformanceField", source)
        self.assertIn("SettingsPerformanceNote", source)
        self.assertIn('group.setObjectName("SettingsPerformanceCard")', source)
        self.assertIn('row_widget.setObjectName("SettingsPerformanceRow")', source)
        self.assertIn('performance_host.setObjectName("SettingsPerformanceHost")', source)
        self.assertIn('performance_content.setObjectName("SettingsPerformanceContent")', source)
        self.assertIn("performance_content.setMaximumWidth(1480)", source)
        self.assertIn('performance_grid_widget.setObjectName("SettingsPerformanceGrid")', source)
        self.assertIn("performance_grid = WrappingLayout(performance_grid_widget, columns=2)", source)
        self.assertIn("QGroupBox#SettingsPerformanceCard", theme_source)
        self.assertIn("QFrame#SettingsPerformanceRow", theme_source)
        self.assertIn('QFrame#SettingsPerformanceRow[firstRow="true"]', theme_source)
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
        self.assertIn("High 128", source)
        self.assertIn('Preview disk cache', source)
        # The remembered-preview count only works through durable packages, so
        # the disk cache being Off has to disable it rather than lie about it.
        self.assertIn("preview_cache_available", source)
        self.assertIn(
            "self.archive_preview_cache_limit_mode_combo.setEnabled(preview_cache_available)",
            source,
        )
        # Nearby prebuilds were removed with the resident migration; the label
        # must not promise them again.
        self.assertNotIn("nearby prebuilds", source)
        self.assertNotIn("prebuilds a few nearby", source)
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
