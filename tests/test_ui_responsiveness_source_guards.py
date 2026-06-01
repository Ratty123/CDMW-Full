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
        self.assertIn("SELECTION_PREVIEW_DEBOUNCE_MS = 160", source)
        self.assertIn("self._selection_preview_timer.timeout.connect(self._refresh_selected_record_previews)", source)
        self.assertIn("def _schedule_selected_record_previews(self) -> None:", source)
        self.assertIn("self._schedule_selected_record_previews()", source)
        selection_start = source.index("def _handle_record_selection(")
        selection_end = source.index("def _schedule_selected_record_previews(", selection_start)
        selection_block = source[selection_start:selection_end]
        self.assertNotIn("self.update_source_preview()", selection_block)
        self.assertNotIn("self.update_final_preview()", selection_block)
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
        self.assertIn('self._refresh_archive_browser_if_pending("tab_activation")', source)
        self.assertIn("def _archive_browser_render_is_ready(self) -> bool:", source)
        self.assertIn("skipped=ready", source)
        self.assertIn("if self._is_tool_visible_or_current(self.research_tab)", source)
        self.assertIn("self.model_library_tab.handle_activated()", source)
        self.assertIn("self.item_icons_tab.schedule_targets_refresh(update_preview=False)", source)

    def test_compare_preview_does_not_autostart_during_startup(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("def _compare_preview_can_autostart(self) -> bool:", source)
        self.assertIn("if self._startup_benchmark_enabled():\n                return False", source)
        refresh_start = source.index("        def refresh_compare_list(")
        refresh_body = source[refresh_start: source.index("        def _handle_compare_selection_change", refresh_start)]
        render_start = source.index("        def _render_compare_preview(")
        render_body = source[render_start: source.index("            texconv_text =", render_start)]
        self.assertIn("if self._startup_benchmark_enabled():\n                self.compare_list.setCurrentRow(-1)", refresh_body)
        self.assertIn("if self._startup_benchmark_enabled():\n                return", render_body)
        self.assertIn('getattr(self, "_startup_splash_window", None) is not None', source)
        self.assertIn("def _queue_current_compare_preview_if_visible(self) -> None:", source)
        self.assertIn("self._queue_current_compare_preview_if_visible()", source)
        handler_start = source.index("        def _handle_compare_selection_change(")
        handler_body = source[handler_start: source.index("        def _flush_pending_compare_preview_selection", handler_start)]
        self.assertIn("if self._compare_preview_can_autostart():", handler_body)
        self.assertNotIn("            self._compare_preview_timer.start()\n\n", handler_body)
        flush_start = source.index("        def _flush_pending_compare_preview_selection")
        flush_body = source[flush_start: source.index("        def current_compare_path_for_research", flush_start)]
        self.assertIn("if not self._compare_preview_can_autostart():", flush_body)

    def test_item_finder_uses_visible_icon_batches_only(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("catalog_filter_timer.setInterval(160)", source)
        self.assertIn("icon_visible_queue_timer.setInterval(80)", source)
        self.assertIn("search_edit.textChanged.connect(lambda _text: catalog_filter_timer.start())", source)
        self.assertIn("category_tree.itemSelectionChanged.connect(lambda: catalog_filter_timer.start())", source)
        self.assertIn("if not dialog.isVisible():\n                    return", source)
        self.assertIn("loaded_count >= 4 or (time.perf_counter() - batch_started_at) >= 0.010", source)
        self.assertIn("allow_sync_prepare=False", source)
        self.assertIn("allow_sync_prepare: bool = False", source)
        self.assertIn("ArchiveItemIconWarmupWorker", source)
        self.assertIn("self._queue_archive_asset_catalog_icon_warmup_rows(", source)
        self.assertIn("self.archive_item_icon_priority_queue: List[Dict[str, object]] = []", source)
        self.assertIn("def _queue_archive_asset_catalog_priority_icon_warmup_rows", source)
        self.assertIn("def _start_archive_item_icon_priority_warmup(self) -> None:", source)
        self.assertIn("thread.finished.connect(lambda generation=generation: self._cleanup_archive_item_icon_priority_refs(generation))", source)
        self.assertIn("self.archive_item_icon_visible_warmup_remaining = 0", source)
        self.assertIn("user_visible: bool = False", source)
        self.assertIn("user_visible=True", source)
        self.assertIn("def _archive_item_icon_lookup_index_missing(self) -> bool:", source)
        self.assertIn("lookup_missing = self._archive_item_icon_lookup_index_missing()", source)
        self.assertIn("if not lookup_missing and self._archive_item_icon_negative_note(prepared_key):", source)
        self.assertIn("self._ensure_archive_basic_index_worker_started()", source)
        self.assertIn("if self._archive_item_icon_lookup_index_missing():\n                self.archive_item_icon_preload_pending_after_ready = True", source)
        self.assertIn("if not self._archive_browser_background_work_allowed() and visible_remaining <= 0:", source)
        self.assertIn("self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)", source)
        self.assertIn("self.archive_item_icon_warmup_user_visible = visible_remaining > 0", source)
        self.assertIn("and not bool(getattr(self, \"archive_item_icon_warmup_user_visible\", False))", source)
        self.assertIn("if self.stop_event.is_set():\n                                    break", source)
        self.assertIn("self.archive_item_icon_negative_cache.clear()", source)
        self.assertIn("self.archive_item_icon_prepared_callbacks.append(_handle_catalog_icon_prepared)", source)
        self.assertIn("self.archive_item_icon_prepared_callbacks.append(_handle_item_finder_donor_icon_prepared)", source)
        self.assertIn("finder_icon_visible_timer.setInterval(80)", source)
        self.assertIn("self.archive_item_icon_negative_cache", source)
        self.assertNotIn("_queue_catalog_row_icons_for_all_shown_rows", source)
        self.assertNotIn("thumb_preload_pending", source)
        self.assertIn('icon_visible_retry_budget = {"remaining": 8}', source)
        self.assertIn("def _catalog_row_prepared_icon_available(row: Mapping[str, object]) -> bool:", source)
        self.assertIn("def _apply_catalog_item_cached_icon(item: QListWidgetItem, row: Mapping[str, object]) -> Tuple[bool, str]:", source)
        self.assertIn('if state == "thumb_pending" and not _catalog_row_prepared_icon_available(row):', source)
        self.assertIn("QTimer.singleShot(90, _queue_catalog_row_icons_for_visible_rows)", source)
        self.assertIn("QTimer.singleShot(300, _queue_catalog_row_icons_for_visible_rows)", source)
        self.assertIn("def _forget_archive_item_icon_pixmap_cache", source)
        self.assertIn("self._forget_archive_item_icon_pixmap_cache(prepared_key)", source)
        self.assertIn("self._forget_archive_item_icon_pixmap_cache(cache_key)", source)
        self.assertIn(
            "if cached_pixmap is None or cached_pixmap.isNull():\n                    self.archive_item_icon_pixmap_cache.pop(cache_key, None)",
            source,
        )
        self.assertIn("pixmap, _note = result", source)
        self.assertNotIn("result = (None, negative_note)", source)
        catalog_callback_index = source.index("self.archive_item_icon_prepared_callbacks.append(_handle_catalog_icon_prepared)")
        catalog_populate_index = source.index("_populate_catalog()", catalog_callback_index)
        self.assertLess(catalog_callback_index, catalog_populate_index)
        preview_start = source.index("            def _refresh_selected_icon_preview() -> None:")
        preview_body = source[preview_start: source.index("            def _handle_catalog_icon_prepared", preview_start)]
        self.assertNotIn("_archive_asset_catalog_preview_pixmap(row, 120)", preview_body)
        self.assertIn("icon_preview.setToolTip(note or \"Icon preview is warming in the background.\")", preview_body)

    def test_resize_path_avoids_expensive_global_recalculation(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        resize_start = source.index("        def _apply_responsive_resize_adjustments(self) -> None:")
        resize_body = source[resize_start: source.index("        def _connect_responsive_screen_signals", resize_start)]
        initial_start = source.index("        def _apply_initial_responsive_window_defaults(self) -> None:")
        initial_body = source[initial_start:resize_start]
        defaults_start = source.index("        def _apply_responsive_window_defaults(")
        defaults_body = source[defaults_start:initial_start]
        self.assertIn("QTimer.singleShot(0, self._apply_initial_responsive_window_defaults)", source)
        self.assertIn("apply_expensive_metrics=False", initial_body)
        self.assertIn("if apply_expensive_metrics:", defaults_body)
        self.assertNotIn("if apply_expensive_metrics or getattr", defaults_body)
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

    def test_startup_archive_autoload_holds_splash_until_search_ready(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertNotIn('not self._preference_bool("auto_load_archive_on_startup", False)', source)
        self.assertIn("browser_view_will_warm_for_startup", source)
        self.assertIn("force_render: bool = False", source)
        self.assertNotIn("_release_startup_after_archive_render", source)
        self.assertIn("force_render=False", source)
        autoload_start = source.index("        if window._startup_archive_autoload_expected():")
        autoload_body = source[autoload_start: source.index("        else:", autoload_start)]
        self.assertNotIn("window._release_startup_splash()", autoload_body)
        startup_load_start = source.index("        def _maybe_autoload_archive_on_startup")
        startup_load_body = source[startup_load_start: source.index("        def _load_game_executable_fingerprints", startup_load_start)]
        self.assertIn("if _previous_session_unclean and not self._startup_benchmark_enabled():", startup_load_body)
        self.assertIn("self._apply_archive_filter_state(self._neutral_archive_filter_state())", startup_load_body)
        self.assertIn('os.environ["CDMW_DEFER_TEXTURE_PREVIEW"] = "1"', source)
        self.assertIn('os.environ.pop("CDMW_DEFER_TEXTURE_PREVIEW", None)', source)
        scan_complete_start = source.index("        def _handle_archive_scan_complete")
        scan_complete_body = source[scan_complete_start: source.index("        def _finalize_archive_scan_complete", scan_complete_start)]
        self.assertIn("def _ensure_archive_extension_index_ready", source)
        self.assertIn("self._ensure_archive_extension_index_ready()", scan_complete_body)
        self.assertNotIn("archive_startup_saved_filter_apply_pending = True", startup_load_body)
        self.assertNotIn("Saved filters will apply when search is ready.", startup_load_body)
        self.assertIn("self.archive_startup_hold_until_ready = True", source)
        self.assertIn("def _maybe_release_startup_after_archive_ready", source)
        self.assertIn("and not bool(getattr(self, \"archive_startup_hold_until_ready\", False))", source)
        self.assertIn("startup_hold or (not browser_visible) or self._archive_browser_background_work_allowed()", source)
        self.assertIn("and self.archive_derived_cache_thread is None", source)
        self.assertIn("and not self.archive_deferred_derived_cache_write_pending", source)
        self.assertIn("def _archive_startup_progress_work_active(self) -> bool:", source)
        self.assertIn("if not self._archive_startup_progress_work_active():", source)
        self.assertIn("getattr(self, \"_startup_splash_release_pending\", False)", source)
        self.assertIn("QTimer.singleShot(1000, self._maybe_release_startup_after_archive_ready)", source)
        self.assertIn("self._startup_splash_progress_detail", source)
        self.assertIn("if startup_deferred_archive_load:", source)
        self.assertIn('worker_extension_filter = "*"', source)
        self.assertIn("worker_view_mode = ARCHIVE_BROWSER_VIEW_MODE", source)
        self.assertIn("build_tree_index=build_browser_tree_index", source)
        self.assertIn("build_category_index=build_browser_category_index", source)
        self.assertIn("not startup_deferred_archive_load\n                and\n                self._archive_folder_tree_enabled()", source)
        self.assertIn("not startup_deferred_archive_load\n                and\n                self._archive_category_view_enabled()", source)
        self.assertIn('_record_runtime_event("startup_autoload_begin"', source)
        self.assertIn('_record_runtime_event("splash_released"', source)
        self.assertIn('_record_runtime_event("main_window_shown"', source)
        self.assertIn("def _schedule_startup_benchmark_search_after_visible", source)
        self.assertIn("def _try_start_startup_benchmark_search_after_visible", source)
        self.assertIn("self._startup_benchmark_search_pending = True", source)
        self.assertIn("or self._startup_archive_first_paint_needed()", source)
        self.assertIn("startup_benchmark_search_ready_after_paint", source)
        self.assertIn('self.archive_browser_preload_state = "ready"', source)
        self.assertIn("self.archive_browser_render_signature = self._current_archive_browser_render_signature()", source)
        self.assertIn("delay_ms = max(1, int(self.archive_selection_state_timer.interval()) + 1)", source)

    def test_archive_refresh_queues_filters_before_first_list(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        scan_start = source.index("        def scan_archives(")
        scan_body = source[scan_start: source.index("        def _set_archive_warmup_overlay", scan_start)]
        complete_start = source.index("        def _handle_archive_scan_complete")
        complete_body = source[complete_start: source.index("        def _finalize_archive_scan_complete", complete_start)]

        self.assertIn("queue_filters_after_first_list = bool(", scan_body)
        self.assertIn("Current filters will apply when search is ready.", scan_body)
        self.assertIn('"filter_text": ""', scan_body)
        self.assertIn('"extension_filter": "*"', scan_body)
        self.assertIn('"view_mode": ARCHIVE_BROWSER_VIEW_MODE', scan_body)
        self.assertIn("Applying queued filters after archive list opened.", source)
        self.assertIn("Filters will apply when search is ready", source)
        self.assertIn("def _archive_filter_state_needs_basic_lookup", source)
        self.assertIn("self._archive_filter_state_needs_basic_lookup(saved_state)", source)
        self.assertIn("self._current_archive_filter_needs_basic_lookup()", source)
        self.assertIn("Filters will apply when archive lookup indexes are ready.", source)
        self.assertNotIn("request_signature or self._current_archive_filter_signature()", complete_body)
        lookup_start = source.index("        def _archive_filter_state_needs_basic_lookup")
        lookup_body = source[lookup_start: source.index("        def _current_archive_filter_needs_path_lookup", lookup_start)]
        self.assertIn("Path lookup is only required for item-name related-file expansion.", lookup_body)
        self.assertIn("return self._archive_filter_state_needs_path_lookup(state)", lookup_body)
        self.assertNotIn("extension_filter and extension_filter not", lookup_body)
        self.assertNotIn("role_filter and role_filter", lookup_body)
        helper_start = source.index("    def _archive_filter_text_explicitly_requests_item_name")
        helper_body = source[helper_start: source.index("    class ArchiveFilterWorker", helper_start)]
        self.assertIn('re.search(r"(^|\\s)name\\s*:"', helper_body)
        self.assertIn('return not any(char in text for char in "/\\\\_*.?[]")', helper_body)
        item_search_start = source.index("        def _archive_saved_filter_needs_item_search")
        item_search_body = source[item_search_start: source.index("        def _archive_filter_state_needs_path_lookup", item_search_start)]
        self.assertIn("_archive_filter_text_needs_item_name_search", item_search_body)
        self.assertIn("def _archive_filter_state_explicitly_requires_item_search", item_search_body)
        self.assertIn("def _archive_filter_state_waits_for_item_search", source)
        self.assertIn("and self._archive_filter_state_explicitly_requires_item_search(state)", source)
        self.assertIn("and not self._startup_benchmark_enabled()", source)
        self.assertNotIn("model_like_extensions", item_search_body)
        self.assertIn("def _schedule_archive_enhanced_index_auto_prewarm", source)
        self.assertIn("def _start_archive_enhanced_index_auto_prewarm", source)
        self.assertIn("self._schedule_archive_enhanced_index_auto_prewarm()", source)
        self.assertIn("Item-name search cache warming after archive list opened.", source)
        self.assertIn("bounded_item_name_python_scan", source)
        self.assertIn("item_name_search_enabled = _archive_filter_text_needs_item_name_search(self.filter_text)", source)
        self.assertIn("item_search_aliases = self.item_search_aliases if item_name_search_enabled else {}", source)
        self.assertIn("len(source_entries) <= 250_000", source)
        self.assertIn("name_search=bounded_python_scan", source)
        self.assertIn("def _archive_filter_can_use_loaded_item_aliases", source)
        self.assertIn("self.archive_item_search_aliases", source)
        self.assertIn("<= 250_000", source)
        apply_start = source.index("        def _apply_archive_filter(self) -> None:")
        apply_body = source[apply_start: source.index("        def _start_archive_filter_worker", apply_start)]
        self.assertIn("self.archive_filter_requested_signature = self._current_archive_filter_signature()", apply_body)
        self.assertIn("self.archive_filters_dirty = False", apply_body)
        pending_start = source.index("        def _apply_pending_archive_enhanced_filter_refresh")
        pending_body = source[pending_start: source.index("        def _mark_archive_filters_dirty", pending_start)]
        self.assertNotIn('self.archive_browser_preload_state != "ready"', pending_body)
        self.assertNotIn("not self.archive_browser_first_visible_paint_done", pending_body)
        run_start = source.index("        @Slot()\n        def run")
        run_body = source[run_start: source.index("    class ArchiveDerivedIndexCacheWriteWorker", run_start)]
        self.assertIn("if entries and self.load_basic_index_cache:", run_body)
        self.assertIn("entries and self.load_basic_index_cache and not basic_indexes_loaded_from_cache", run_body)
        self.assertNotIn("self.load_basic_index_cache or not can_use_initial_list", run_body)

    def test_archive_click_lag_preload_state_guards_ready_render(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        activation_start = source.index("        def _handle_tool_activated(self, widget: QWidget) -> None:")
        activation_body = source[activation_start: source.index("        def show_settings", activation_start)]
        refresh_start = source.index("        def _refresh_archive_browser_if_pending(")
        refresh_body = source[refresh_start: source.index("        def _refresh_or_defer_archive_browser_view", refresh_start)]
        self.assertIn("self.archive_browser_first_visible_started_at = time.perf_counter()", activation_body)
        self.assertIn("if self._archive_browser_render_is_ready():", activation_body)
        self.assertNotIn("_schedule_archive_pending_enhanced_filter_refresh", activation_body)
        self.assertIn("def _schedule_archive_browser_first_visible_paint_marker", source)
        self.assertIn("not self.isVisible() or not self._is_tool_visible_or_current(self.archive_browser_tab)", source)
        self.assertIn("QTimer.singleShot(max(0, int(delay_ms)), self._handle_archive_browser_first_visible_paint)", source)
        self.assertIn("def _refresh_archive_browser_view_stage_controls", source)
        self.assertIn("def _refresh_archive_browser_view_stage_populate", source)
        controls_start = source.index("        def _refresh_archive_browser_view_stage_controls")
        controls_body = source[controls_start: source.index("        def _refresh_archive_browser_view_stage_populate", controls_start)]
        self.assertIn("defer_missing_children=True", controls_body)
        self.assertNotIn("build_archive_structure_children_map(self.archive_entries)", controls_body)
        self.assertIn('self._log_archive_browser_render_stage("model_reset"', source)
        self.assertIn("if self._archive_browser_render_is_ready():", refresh_body)
        self.assertIn("self.archive_browser_refresh_pending = False", refresh_body)
        self.assertNotIn("skipped=population_active", refresh_body)
        self.assertIn("pending_refresh=start", refresh_body)

    def test_startup_splash_waits_for_archive_first_paint(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        finish_start = source.index("        def _finish_startup_splash_and_show_main_window")
        finish_body = source[finish_start: source.index("        def _release_startup_splash", finish_start)]
        first_paint_start = source.index("        def _handle_archive_browser_first_visible_paint")
        first_paint_body = source[first_paint_start: source.index("        def _try_apply_startup_saved_filters", first_paint_start)]

        self.assertIn("Qt.WindowStaysOnTopHint", source)
        self.assertIn('if not os.environ.get("_PYI_SPLASH_IPC"):', source)
        self.assertIn("def _finish_startup_splash_after_main_window_paint", source)
        self.assertIn("self._show_main_window_after_startup_splash()", finish_body)
        self.assertNotIn("self._finish_startup_splash_now()\n            self._show_main_window_after_startup_splash()", finish_body)
        self.assertIn("self._startup_splash_finish_after_paint_deadline = time.monotonic() + 10.0", finish_body)
        self.assertIn("self.archive_browser_first_visible_paint_done = False", finish_body)
        self.assertIn("self._schedule_startup_splash_finish_after_main_window_paint(180)", finish_body)
        self.assertIn("not bool(getattr(self, \"_startup_splash_finish_pending\", False))", source)
        self.assertIn("_startup_splash_finish_after_paint_deadline", first_paint_body)
        self.assertIn('self._update_startup_splash("Opening Archive Browser...", 0, 0)', source)
        self.assertIn('startup_splash_first_paint_timeout', source)
        self.assertIn("self._schedule_startup_splash_finish_after_main_window_paint(80)", first_paint_body)

    def test_archive_context_menu_does_not_auto_preview_or_build_family_graph(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        model_source = _read("cdmw/ui/archive_browser_model.py")
        menu_start = source.index("        def _show_archive_tree_context_menu(self, position) -> None:")
        menu_body = source[menu_start: source.index("        def _apply_archive_patch_result", menu_start)]
        selection_start = source.index("        def _handle_archive_current_item_change(")
        selection_body = source[selection_start: source.index("        def _schedule_archive_selection_state_update", selection_start)]
        filter_finalize_start = source.index("        def _finalize_archive_filter_complete(")
        filter_finalize_body = source[filter_finalize_start: source.index("        def _archive_tree_item_kind", filter_finalize_start)]
        self.assertIn("def mousePressEvent(self, event) -> None:", model_source)
        self.assertIn("if event.button() == Qt.RightButton:", model_source)
        self.assertIn("event.accept()", model_source)
        self.assertIn("archive_context_menu_selection_suppressed", source)
        self.assertIn("self.archive_context_menu_selection_suppressed = True", menu_body)
        self.assertIn("self.archive_context_menu_selection_suppressed = False", menu_body)
        self.assertIn("if bool(getattr(self, \"archive_context_menu_selection_suppressed\", False)):", selection_body)
        self.assertIn('menu.addSection(menu_icons[kind], label)', menu_body)
        self.assertIn('"View + Inspect"', menu_body)
        self.assertIn('"File"', menu_body)
        self.assertIn('"Copy Filename"', menu_body)
        self.assertIn("QApplication.clipboard().setText(current_entry.basename)", menu_body)
        self.assertIn("preview_action.triggered.connect(lambda _checked=False, current_entry=entry: self._render_archive_preview(current_entry))", menu_body)
        self.assertNotIn("self._render_archive_preview(entry)", menu_body)
        self.assertNotIn("_archive_hkx_placement_candidates_for_entry(entry)", menu_body)
        self.assertIn("if entry.extension in ARCHIVE_AUDIO_PATCH_EXTENSIONS:", menu_body)
        self.assertIn("import_audio_action.triggered.connect(", menu_body)
        self.assertIn("Archive context menu timing | build=", menu_body)

    def test_archive_model_click_preview_work_is_worker_owned(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        selection_start = source.index("        def _handle_archive_current_item_change(")
        selection_body = source[selection_start: source.index("        def _schedule_archive_selection_state_update", selection_start)]
        render_start = source.index("        def _render_archive_preview(")
        render_body = source[render_start: source.index("        def _flush_scheduled_archive_preview_request", render_start)]
        flush_start = source.index("        def _flush_scheduled_archive_preview_request(")
        flush_body = source[flush_start: source.index("        def _archive_native_prefetch_candidate_entries", flush_start)]
        filter_finalize_start = source.index("        def _finalize_archive_filter_complete(")
        filter_finalize_body = source[filter_finalize_start: source.index("        def _archive_tree_item_kind", filter_finalize_start)]

        self.assertIn("self._render_archive_preview(entry)", selection_body)
        self.assertIn("if self._startup_benchmark_enabled():", selection_body)
        self.assertIn("or self._startup_benchmark_enabled()", filter_finalize_body)
        self.assertIn("self._show_archive_preview_loading_state(entry)", render_body)
        self.assertIn("preview_cache_snapshot = {", flush_body)
        self.assertIn("full_cache_key=cache_key", flush_body)
        self.assertIn("fast_cache_key=fast_cache_key", flush_body)
        self.assertIn("emit_quick_preview=(", flush_body)
        self.assertNotIn("self._get_cached_archive_preview_result(", flush_body)
        self.assertNotIn("self._get_durable_native_preview_package_result(", flush_body)
        self.assertNotIn("self._quick_archive_model_preview_result(", flush_body)
        self.assertNotIn("self._apply_archive_preview_result(", flush_body)

    def test_archive_preview_reference_pane_is_deferred(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        show_start = source.index("        def _show_archive_preview_result(")
        show_body = source[show_start: source.index("        def _toggle_archive_loose_preview", show_start)]
        flush_start = source.index("        def _flush_archive_texture_reference_update(")
        flush_body = source[flush_start: source.index("        def _show_archive_preview_loading_state", flush_start)]

        self.assertIn("self.archive_texture_reference_update_timer.setInterval(16)", source)
        self.assertIn("self._schedule_archive_texture_reference_update(", show_body)
        self.assertNotIn("_populate_archive_texture_reference_list(result.model_texture_references", show_body)
        self.assertIn("enrich=False", flush_body)
        self.assertIn("self._clear_archive_texture_reference_views()", source)

    def test_archive_background_work_waits_for_browser_ready_or_first_paint(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        allowed_start = source.index("        def _archive_browser_background_work_allowed(self) -> bool:")
        allowed_body = source[allowed_start: source.index("        def _schedule_archive_post_ready_background_work", allowed_start)]
        finalize_start = source.index("        def _finalize_archive_scan_complete(")
        finalize_body = source[finalize_start: source.index("        def _start_archive_basic_index_worker", finalize_start)]
        icon_start = source.index("        def _schedule_archive_asset_catalog_icon_preload")
        icon_body = source[icon_start: source.index("        def _queue_archive_asset_catalog_icon_warmup_rows", icon_start)]
        self.assertIn('self.archive_browser_preload_state != "ready"', allowed_body)
        self.assertIn("self.archive_browser_first_visible_paint_done", allowed_body)
        self.assertIn("return False", allowed_body)
        self.assertNotIn("self.archive_browser_ready_at", allowed_body)
        self.assertIn("self.archive_deferred_basic_index_start_pending = bool(prewarm_basic_index)", source)
        self.assertIn("self.archive_deferred_enhanced_index_start_pending = bool(prewarm_enhanced_index)", source)
        self.assertIn("self.archive_deferred_sidecar_start_pending = True", finalize_body)
        self.assertIn("self._schedule_archive_post_ready_background_work()", finalize_body)
        self.assertIn("self._start_archive_basic_index_worker()", source)
        self.assertIn("if not self._archive_browser_background_work_allowed():", icon_body)
        self.assertIn("self.archive_item_icon_preload_pending_after_ready = bool(self.archive_item_asset_catalog)", icon_body)
        self.assertIn("if self._archive_item_icon_lookup_index_missing():", icon_body)
        self.assertIn("self._ensure_archive_basic_index_worker_started()", icon_body)

    def test_startup_splash_progress_uses_single_text_source(self) -> None:
        source = _read("cdmw/ui/startup_splash_host.py")
        self.assertIn("self.detail_label.setMaximumHeight(34)", source)
        self.assertNotIn("self.progress_label = QLabel", source)
        self.assertNotIn("self.progress_label.setText", source)
        self.assertNotIn('f"{self._current:,} / {self._total:,}"', source)
        self.assertNotIn("painter.drawText(QRectF(rail.left(), rail.top() - 20", source)

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

    def test_research_archive_picker_details_uses_highlighted_editor(self) -> None:
        source = _read("cdmw/ui/research_tab.py")
        self.assertIn("ArchiveDetailsEditor", source)
        self.assertIn("self.archive_picker_preview_details_edit = ArchiveDetailsEditor(", source)
        self.assertIn("color_scheme=self._current_preview_color_scheme()", source)
        self.assertIn("def _apply_archive_picker_preview_text_style(self) -> None:", source)
        self.assertIn("preview_scheme = self._current_preview_color_scheme()", source)
        self.assertIn("self.archive_picker_preview_details_edit.set_theme(self.current_theme_key)", source)

    def test_archive_browser_uses_virtual_model_not_legacy_tree_population(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("def _populate_archive_virtual_tree(", source)
        self.assertIn("self.archive_tree.set_archive_state(", source)
        self.assertNotIn("def _begin_archive_tree_clear(", source)
        self.assertNotIn("self.archive_tree_clear_timer.setInterval(12)", source)
        self.assertNotIn("def _continue_archive_tree_clear(self) -> None:", source)
        self.assertNotIn("self.archive_tree.takeTopLevelItem(0)", source)

    def test_archive_ready_avoids_ui_thread_full_archive_scans(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        busy_start = source.index("        def set_busy(")
        busy_body = source[busy_start: source.index("        def reset_progress", busy_start)]
        self.assertIn('filtered_has_dds = int(getattr(self, "archive_filtered_dds_count", 0) or 0) > 0', busy_body)
        self.assertNotIn('any(entry.extension == ".dds" for entry in self.archive_filtered_entries)', busy_body)
        self.assertNotIn("ArchiveEnhancedIndexWorker(tuple(self.archive_entries))", source)
        self.assertNotIn("ArchiveStructureFilterWorker(tuple(self.archive_entries))", source)

    def test_archive_search_preserves_left_controls_scroll_position(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("self.archive_controls_scroll_filter_anchor: Optional[int] = None", source)
        self.assertIn("def _capture_archive_controls_scroll_for_filter(self) -> None:", source)
        self.assertIn("def _restore_archive_controls_scroll_after_filter(self) -> None:", source)
        self.assertIn("QTimer.singleShot(80, _restore)", source)

        apply_start = source.index("        def _apply_archive_filter(self) -> None:")
        apply_body = source[apply_start: source.index("        def _start_archive_filter_worker", apply_start)]
        self.assertIn("self._capture_archive_controls_scroll_for_filter()", apply_body)

        worker_start = source.index("        def _start_archive_filter_worker(")
        worker_body = source[worker_start: source.index("        def _handle_archive_filter_complete", worker_start)]
        self.assertIn("self.set_busy(True, build_mode=False)", worker_body)
        self.assertIn("self._restore_archive_controls_scroll_after_filter()", worker_body)

        complete_start = source.index("        def _handle_archive_filter_complete(")
        complete_body = source[complete_start: source.index("        def _finalize_archive_filter_complete", complete_start)]
        self.assertIn("Rendering archive browser view...", complete_body)
        self.assertIn("self._restore_archive_controls_scroll_after_filter()", complete_body)

        finish_start = source.index("            def finish_filter_render() -> None:")
        finish_body = source[finish_start: source.index("            defer_default_selection =", finish_start)]
        self.assertIn("self._restore_archive_controls_scroll_after_filter()", finish_body)
        self.assertIn("self.archive_controls_scroll_filter_anchor = None", finish_body)

    def test_archive_asset_family_graph_cache_is_bounded_and_logged(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        self.assertIn("self.archive_asset_family_cache: OrderedDict", source)
        self.assertIn("self.archive_asset_family_cache_limit = 512", source)
        self.assertIn("def _archive_asset_family_cache_key", source)
        self.assertIn("def _remember_archive_asset_family_graph", source)
        self.assertIn("Asset family cache hit:", source)
        self.assertIn("Asset family cache miss; rebuilding:", source)

    def test_placement_workspace_prepares_off_ui_thread(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        workspace_start = source.index("        def _open_archive_attachment_placement_workspace_dialog(")
        workspace_body = source[workspace_start: source.index("        def _open_archive_attachment_donor_picker_dialog", workspace_start)]
        self.assertIn("_run_archive_attachment_placement_prepare(", workspace_body)
        self.assertIn("self._run_utility_task(", workspace_body)
        self.assertNotIn("_open_archive_attachment_placement_diff_dialog(source_entry, None)", workspace_body)

    def test_placement_source_choice_refreshes_in_place(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        diff_start = source.index("        def _open_archive_attachment_placement_diff_dialog(")
        choose_start = source.index("            def _choose_placement_source_from_workspace()", diff_start)
        choose_body = source[choose_start: source.index("            def _apply_default_swap_type()", choose_start)]
        self.assertIn("Loading placement comparison", choose_body)
        self.assertIn("_run_archive_attachment_placement_prepare(", choose_body)
        self.assertIn("_apply_prepared_placement_source", choose_body)
        self.assertIn("_set_placement_source_loading(True", choose_body)
        self.assertNotIn("dialog.accept()", choose_body)

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
