from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class UIResponsivenessSourceGuards(unittest.TestCase):
    def test_icon_creator_filters_are_debounced_and_batched(self) -> None:
        source = _read("cdmw/ui/item_icons_tab.py")
        self.assertIn("RECORD_FILTER_DEBOUNCE_MS = 120", source)
        self.assertIn("RECORD_POPULATION_BATCH_SIZE = 250", source)
        self.assertIn("self._record_filter_timer.timeout.connect(self._populate_records_tree)", source)
        self.assertIn("self._record_population_timer.timeout.connect(self._flush_record_population_batch)", source)
        self.assertIn("self.records_tree.addTopLevelItems(items)", source)
        self.assertIn("self.records_tree.setSortingEnabled(False)", source)
        self.assertIn("self.target_filter_edit.textChanged.connect(lambda _text=\"\": self._target_filter_timer.start())", source)
        self.assertIn("self._target_refresh_timer.timeout.connect(self._flush_scheduled_target_refresh)", source)
        self.assertIn("def schedule_targets_refresh(self, *, update_preview: bool = False) -> None:", source)
        self.assertIn("signature == self._target_entries_signature", source)

    def test_model_library_results_are_debounced_and_batched(self) -> None:
        source = _read("cdmw/ui/model_library_tab.py")
        self.assertIn("RESULTS_FILTER_DEBOUNCE_MS = 140", source)
        self.assertIn("RESULTS_POPULATION_BATCH_SIZE = 200", source)
        self.assertIn("self._results_filter_timer.timeout.connect(self._flush_debounced_results_filter)", source)
        self.assertIn("self._results_population_timer.timeout.connect(self._flush_results_population_batch)", source)
        self.assertIn("self._activation_preview_timer.timeout.connect(self._schedule_auto_inline_preview)", source)
        self.assertIn("self._schedule_results_filter()", source)
        self.assertIn("if self._populating_results:\n            return", source)
        self.assertIn("if not self.isVisible():\n            return", source)
        self.assertIn("def handle_activated(self) -> None:", source)
        self.assertIn("self.results_tree.addTopLevelItems(items)", source)

    def test_asset_tab_activation_defers_heavy_refresh_work(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("if self._is_tool_visible_or_current(self.archive_browser_tab)", source)
        self.assertIn("if self._is_tool_visible_or_current(self.research_tab)", source)
        self.assertIn("self.model_library_tab.handle_activated()", source)
        self.assertIn("self.item_icons_tab.schedule_targets_refresh(update_preview=False)", source)

    def test_item_finder_uses_visible_icon_batches_only(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("catalog_filter_timer.setInterval(160)", source)
        self.assertIn("search_edit.textChanged.connect(lambda _text: catalog_filter_timer.start())", source)
        self.assertIn("category_tree.itemSelectionChanged.connect(lambda: catalog_filter_timer.start())", source)
        self.assertIn("if not dialog.isVisible():\n                    return", source)
        self.assertIn("loaded_count >= 4 or (time.perf_counter() - batch_started_at) >= 0.010", source)
        self.assertIn("allow_sync_prepare=False", source)
        self.assertIn("ArchiveItemIconWarmupWorker", source)
        self.assertIn("self._queue_archive_asset_catalog_icon_warmup_rows(", source)
        self.assertNotIn("_queue_catalog_row_icons_for_all_shown_rows", source)
        self.assertNotIn("thumb_preload_pending", source)

    def test_resize_path_avoids_expensive_global_recalculation(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        resize_start = source.index("        def _apply_responsive_resize_adjustments(self) -> None:")
        resize_body = source[resize_start: source.index("        def _connect_responsive_screen_signals", resize_start)]
        self.assertIn("apply_expensive_metrics=False", resize_body)
        self.assertIn("def _cache_responsive_control_widgets(self) -> None:", source)
        self.assertIn("self._responsive_control_widgets", source)
        self.assertIn("or getattr(self, \"_applying_responsive_layout\", False)", source)

    def test_item_finder_persists_location_and_layout(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn('"ui/item_finder_geometry"', source)
        self.assertIn('"ui/item_finder_splitter_sizes"', source)
        self.assertIn('"ui/item_finder_search_text"', source)
        self.assertIn('"ui/item_finder_category"', source)
        self.assertIn('"ui/item_finder_group"', source)
        self.assertIn('"ui/item_finder_selected_key"', source)
        self.assertIn('"ui/item_finder_scroll_value"', source)

    def test_startup_archive_preload_renders_browser_while_hidden(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertNotIn('not self._preference_bool("auto_load_archive_on_startup", False)', source)
        self.assertIn("browser_view_will_warm_for_startup", source)
        self.assertIn("force_startup_archive_render", source)
        self.assertIn("force_render: bool = False", source)

    def test_hidden_model_previews_stop_background_render_timers(self) -> None:
        widgets = _read("cdmw/ui/widgets.py")
        main_window = _read("cdmw/ui/main_window.py")
        self.assertIn("def pause_interactive_timers(self) -> None:", widgets)
        self.assertIn("def hideEvent(self, event) -> None:", widgets)
        self.assertIn("self.pause_interactive_timers()", widgets)
        self.assertIn("visible = self.isVisible() and (self.window() is None or self.window().isVisible())", widgets)
        self.assertIn("if not self.isVisible():\n            self._pan_drag_active = False", widgets)
        self.assertIn("def _deactivate_archive_model_renderers_for_non_model_preview(self) -> None:", main_window)
        self.assertIn("def _cancel_archive_isolated_package_worker_for_non_model_preview(self) -> None:", main_window)
        self.assertIn("self.archive_isolated_package_pending_result = None", main_window)
        self.assertIn("worker.stop()", main_window)
        self.assertIn("self._shutdown_archive_isolated_renderer_host()", main_window)
        self.assertIn("self._deactivate_archive_model_renderers_for_non_model_preview()", main_window)

    def test_research_archive_picker_flat_view_is_batched(self) -> None:
        source = _read("cdmw/ui/research_tab.py")
        self.assertIn("ARCHIVE_PICKER_POPULATION_BATCH_SIZE = 250", source)
        self.assertIn("self._archive_picker_population_timer.timeout.connect(self._flush_archive_picker_population_batch)", source)
        self.assertIn("def _flush_archive_picker_population_batch(self) -> None:", source)
        self.assertIn("self._archive_picker_population_timer.start()", source)

    def test_archive_browser_clear_and_expansion_are_progressive(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("def _begin_archive_tree_clear(self, on_complete: Callable[[], None]) -> bool:", source)
        self.assertIn("self.archive_tree_clear_timer.start()", source)
        self.assertIn("def _continue_archive_tree_clear(self) -> None:", source)
        self.assertIn("self.archive_tree.takeTopLevelItem(0)", source)
        self.assertIn("clear_children: bool = True", source)
        self.assertIn("clear_children=False", source)

    def test_preview_limits_and_timers_target_interactive_frame_budget(self) -> None:
        text_search = _read("cdmw/ui/text_search_tab.py")
        widgets = _read("cdmw/ui/widgets.py")
        texture_editor = _read("cdmw/ui/texture_editor_tab.py")
        self.assertIn("PREVIEW_DISPLAY_CHAR_LIMIT = 750_000", text_search)
        self.assertIn("SYNTAX_HIGHLIGHT_CHAR_LIMIT = 250_000", text_search)
        self.assertIn("MATCH_HIGHLIGHT_CHAR_LIMIT = 250_000", text_search)
        self.assertIn("Preview truncated to", text_search)
        self.assertIn("self._interactive_scale_timer.setInterval(16)", widgets)
        self.assertIn("self._physics_simulation_timer.setInterval(16)", widgets)
        self.assertIn("self._adjustment_preview_timer.setInterval(16)", texture_editor)
        self.assertIn("self._coalesced_ui_refresh_timer.setInterval(16)", texture_editor)
        self.assertIn("self.vertical_guides_edit.textChanged.connect(lambda *_args: self._schedule_coalesced_ui_refresh())", texture_editor)


if __name__ == "__main__":
    unittest.main()
