from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "cdmw_app.py"
MAIN_WINDOW = ROOT / "cdmw" / "ui" / "main_window.py"
ARCHIVE = ROOT / "cdmw" / "core" / "archive.py"
THEMES = ROOT / "cdmw" / "ui" / "themes.py"


class CrashReportingGuardTests(unittest.TestCase):
    def test_bootstrap_import_failures_are_reported(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("def _write_bootstrap_report", source)
        self.assertIn('"bootstrap_failure"', source)
        self.assertIn("from cdmw.ui.main_window import run_gui", source)

    def test_gui_has_heartbeat_and_hang_watchdog(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("heartbeat_path = crash_reports_dir / \"app_heartbeat.json\"", source)
        self.assertIn("def _check_previous_unclean_exit", source)
        self.assertIn("def _process_is_alive", source)
        self.assertIn("previous_pid_alive", source)
        self.assertIn("def _start_hang_watchdog", source)
        self.assertIn('"app_hang_detected"', source)
        self.assertIn('"previous_session_unclean_exit"', source)
        self.assertIn("faulthandler.enable", source)

    def test_background_crash_context_does_not_read_live_qt_widgets(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("_cached_crash_context", source)
        self.assertIn("app.thread() != QThread.currentThread()", source)
        self.assertIn("context.update(_cached_crash_context)", source)

    def test_close_waits_for_workers_asynchronously(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("def _begin_deferred_close_for_workers", source)
        self.assertIn("event.ignore()", source)
        self.assertIn("thread.finished.connect(self._finish_deferred_close_if_workers_stopped", source)
        self.assertIn("self._close_force_accept = True", source)
        self.assertNotIn("thread.wait(wait_ms)", source)
        self.assertNotIn("wait_ms: int = 1200", source)

    def test_archive_scan_breadcrumbs_are_recorded_for_native_faults(self) -> None:
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")
        archive_source = ARCHIVE.read_text(encoding="utf-8")
        self.assertIn("archive_scan_breadcrumb.json", main_source)
        self.assertIn("def _write_scan_breadcrumb", main_source)
        self.assertIn("on_breadcrumb=self._write_scan_breadcrumb", main_source)
        self.assertIn("on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]]", archive_source)
        self.assertIn('"phase": "parse_archive_pamt"', archive_source)
        self.assertIn('"pamt_path": str(pamt_path)', archive_source)

    def test_archive_scan_progress_is_not_emitted_from_nested_python_thread(self) -> None:
        archive_source = ARCHIVE.read_text(encoding="utf-8")
        self.assertNotIn("emit_parse_heartbeat", archive_source)
        self.assertNotIn("heartbeat_thread = threading.Thread", archive_source)
        self.assertNotIn("heartbeat_stop = threading.Event()", archive_source)

    def test_archive_pamt_parser_avoids_giant_record_lists(self) -> None:
        archive_source = ARCHIVE.read_text(encoding="utf-8")
        self.assertIn("max_cache_entries: int = 200_000", archive_source)
        self.assertIn("seen_offsets: set[int] = set()", archive_source)
        self.assertIn("file_table = memoryview(data)[off : off + file_table_size]", archive_source)
        self.assertIn('struct.iter_unpack("<IIIIHH", file_table)', archive_source)
        self.assertNotIn('files = list(struct.iter_unpack("<IIIIHH"', archive_source)

    def test_archive_preview_inner_splitter_collapses_references_before_overlap(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("archive_preview_main_widget.setMinimumWidth(0)", source)
        self.assertIn("self.archive_preview_title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)", source)
        self.assertIn("self.archive_texture_refs_group.setMinimumWidth(0)", source)
        self.assertIn("self.archive_preview_content_splitter.setChildrenCollapsible(True)", source)
        self.assertIn("def _clamp_archive_preview_asset_map_splitter(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("min_preview_width = 640", source)
        self.assertIn("min_refs_width = 260", source)
        self.assertIn("max_refs_width = min(760", source)
        self.assertIn("target_sizes = [total, 0]", source)
        self.assertIn("self.archive_preview_content_splitter.setSizes(target_sizes)", source)

    def test_loose_preview_toggle_is_two_state_action(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("def _toggle_archive_loose_preview", source)
        self.assertIn("self.archive_preview_requested_loose = not bool(self.archive_preview_showing_loose)", source)
        self.assertIn("self._show_archive_preview_result(result, use_loose=self.archive_preview_requested_loose)", source)
        self.assertIn('"Archive File" if self.archive_preview_showing_loose else "Loose File"', source)
        self.assertNotIn("def _toggle_archive_loose_preview(self) -> None:\n            self.archive_preview_requested_loose = False", source)

    def test_archive_preview_refresh_respects_loose_asset_arguments(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("include_loose_preview_assets=include_loose_preview_assets", source)
        self.assertIn("prefer_loose_preview=self.archive_preview_requested_loose", source)
        self.assertIn("self.archive_preview_requested_loose = bool(entry is not None and prefer_loose_preview)", source)
        self.assertNotIn("include_loose_preview_assets = False\n            prefer_loose_preview = False", source)

    def test_floating_preview_settings_syncs_back_to_settings_tab(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("def _sync_model_preview_settings_controls", source)
        self.assertIn("settings_tab._apply_model_preview_controls(settings)", source)
        self.assertIn("dialog.set_settings(settings)", source)
        self.assertIn("self._sync_model_preview_settings_controls()", source)

    def test_startup_splash_has_abstract_animation(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("class StartupSignalMark", source)
        self.assertIn("_CDMW_GLYPHS", source)
        self.assertIn("def _draw_cdmw_pixel_build", source)
        self.assertIn("build_speed = 1.62", source)
        self.assertIn("self._timer = QTimer(self)", source)
        self.assertIn("def paintEvent(self, event) -> None", source)
        self.assertIn("self.signal_mark = StartupSignalMark", source)
        self.assertIn("self.signal_mark.stop()", source)
        self.assertIn("remaining_minimum_visible_ms", source)
        self.assertIn("self._minimum_visible_seconds = 3.0", source)
        self.assertIn("QTimer.singleShot(remaining_ms, self._release_startup_splash)", source)
        self.assertIn("def pump_animation_frame", source)
        self.assertIn("MainWindow(startup_splash=startup_splash)", source)
        self.assertIn('pump_startup_splash("Preparing archive browser...")', source)
        self.assertIn("#c56d43", source)
        self.assertNotIn("compass_radius", source)
        self.assertNotIn("route = QPainterPath()", source)
        self.assertNotIn("Qt.DashLine", source)
        self.assertIn("QFrame#StartupSignalMark", source)
        self.assertNotIn('QLabel("CDMW")', source)

    def test_crimson_desert_theme_is_available(self) -> None:
        source = THEMES.read_text(encoding="utf-8")
        self.assertIn('"crimson_desert"', source)
        self.assertIn('"label": "Crimson Desert"', source)
        self.assertIn('"accent": "#c56d43"', source)

    def test_main_window_has_about_license_tab(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        menu_order = [
            'self.profile_menu = menu_bar.addMenu("Profile")',
            'self.open_settings_action = menu_bar.addAction("Settings")',
            'self.window_menu = menu_bar.addMenu("Window")',
            'self.help_menu = menu_bar.addMenu("Help")',
            'self.open_about_action = menu_bar.addAction("About")',
        ]
        menu_positions = [source.index(marker) for marker in menu_order]
        self.assertEqual(menu_positions, sorted(menu_positions))
        self.assertIn('self.quick_start_menu_action = self.help_menu.addAction("Quick Start")', source)
        self.assertIn('self.open_documentation_action = self.help_menu.addAction("Documentation")', source)
        self.assertIn("self.open_settings_action.triggered.connect(self.show_settings)", source)
        self.assertIn("def show_settings(self, _checked: bool = False) -> None:", source)
        self.assertIn("settings_tab_index = self.main_tabs.addTab(self.settings_tab, \"Settings\")", source)
        self.assertIn("self.main_tabs.setTabVisible(settings_tab_index, False)", source)
        self.assertIn('self.open_about_action = menu_bar.addAction("About")', source)
        self.assertIn("def _build_about_page(self) -> QWidget:", source)
        self.assertIn("def show_about_dialog(self, _checked: bool = False) -> None:", source)
        self.assertIn("def show_documentation_dialog(self, _checked: bool = False, topic_id: str = \"\") -> None:", source)
        self.assertNotIn("support_menu_action", source)
        self.assertNotIn('self.main_tabs.addTab(self.about_tab, "About")', source)
        self.assertNotIn('about_tabs.addTab(docs_page, "Documentation")', source)
        self.assertIn('about_tabs.addTab(license_page, "License")', source)
        self.assertIn("def _read_license_text(self) -> str:", source)
        self.assertIn('self._read_project_text_file(\n                "LICENSE"', source)
        self.assertIn("license_edit.setPlainText(self._read_license_text())", source)

    def test_settings_page_uses_left_navigation(self) -> None:
        settings_source = (ROOT / "cdmw" / "ui" / "settings_tab.py").read_text(encoding="utf-8")
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.section_nav_list = QListWidget()", settings_source)
        self.assertIn("self.section_stack = QStackedWidget()", settings_source)
        for title in (
            '"Setup"',
            '"Paths"',
            '"Archive Browser Performance"',
            '"Appearance"',
            '"Layout"',
            '"Safety"',
        ):
            self.assertIn(title, settings_source)
        self.assertIn("self.setup_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.paths_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.archive_performance_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.appearance_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.layout_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.safety_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.setup_page_layout.insertWidget(2, setup_section)", settings_source)
        self.assertIn("self.paths_page_layout.insertWidget(2, paths_section)", settings_source)
        self.assertIn("self.paths_page_layout.insertWidget(3, archive_locations_section)", settings_source)
        self.assertIn("def show_settings_section(self, key: str) -> None:", settings_source)
        self.assertIn('self.settings_tab.show_settings_section("setup")', main_source)
        self.assertIn('self.settings_tab.show_settings_section("paths")', main_source)

    def test_archive_browser_has_asset_catalog_scope_dialog(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn('self.archive_asset_catalog_button = QPushButton("Item Finder")', source)
        self.assertIn('self.archive_clear_asset_scope_button = QPushButton("Clear Scope")', source)
        self.assertIn("def _show_archive_asset_catalog_dialog(self) -> None:", source)
        self.assertIn(
            "def _apply_archive_asset_catalog_scope(self, row: Mapping[str, object], *, include_related: bool = True) -> None:",
            source,
        )
        self.assertIn("def _resolve_archive_asset_catalog_scope_entries(", source)
        self.assertIn("def _archive_asset_catalog_preview_pixmap(", source)
        self.assertIn("def _archive_asset_catalog_inventory_icon_pixmap(", source)
        self.assertIn("category_tree.setHeaderHidden(True)", source)
        self.assertIn("item_grid.setViewMode(QListView.ViewMode.IconMode)", source)
        self.assertIn("item_grid.setIconSize(QSize(86, 86))", source)
        self.assertIn("icon_row_timer.timeout.connect(_load_next_catalog_row_icon)", source)
        self.assertIn("def _apply_archive_direct_scope(", source)
        self.assertIn("def _clear_archive_asset_catalog_scope(self) -> None:", source)
        self.assertIn("linked_tree.setHeaderLabels([\"Linked files\", \"Path\"])", source)
        self.assertIn('exact_scope_button = QPushButton("Show Exact Links")', source)
        self.assertIn('scope_button = QPushButton("Show Related Set")', source)
        self.assertIn("include_related: bool = True", source)
        self.assertIn("def _archive_asset_catalog_group_choices(self, category: str = \"\") -> Tuple[str, ...]:", source)
        self.assertIn("no full archive scan", source)
        self.assertIn("Item Finder scoped Archive Browser to:", source)
        self.assertIn('self.archive_texture_scope_all_button = QPushButton("Show File Set")', source)
        self.assertIn("def _scope_all_archive_texture_references(self) -> None:", source)
        self.assertIn("Referenced file set scoped Archive Browser to:", source)

    def test_archive_extension_filter_is_searchable_for_rare_extensions(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("self.archive_extension_filter_combo.setEditable(True)", source)
        self.assertIn("self.archive_extension_filter_combo.setInsertPolicy(QComboBox.NoInsert)", source)
        self.assertIn("self.archive_extension_filter_combo.setMaxVisibleItems(32)", source)
        self.assertIn("self.archive_extension_filter_combo.setMinimumWidth(210)", source)
        self.assertIn('extension_line_edit.setPlaceholderText("Select or type extension")', source)
        self.assertIn("type a specific extension directly", source)
        self.assertIn("self.archive_extension_picker_button = QToolButton()", source)
        self.assertIn("self.archive_extension_picker_button.clicked.connect(self.archive_extension_filter_combo.showPopup)", source)
        self.assertIn('archive_extension_filter_label = QLabel("Extension")', source)
        self.assertIn("self.archive_extension_filter_combo.currentTextChanged.connect(self._mark_archive_filters_dirty)", source)

    def test_archive_controls_sidebar_keeps_readable_width(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("def _archive_controls_sidebar_bounds(self) -> Tuple[int, int, int]:", source)
        self.assertIn("readable_min = int(round(440 * scale))", source)
        self.assertIn("archive_controls_min, _archive_controls_pref, archive_controls_max = self._archive_controls_sidebar_bounds()", source)
        self.assertIn("self.archive_extension_picker_button.setEnabled(not busy)", source)

    def test_additional_qa_themes_are_available(self) -> None:
        source = THEMES.read_text(encoding="utf-8")
        for key, label in (
            ("midnight_ember", "Midnight Ember"),
            ("glacier", "Glacier"),
            ("black_gold", "Black Gold"),
            ("pine", "Pine"),
            ("violet_steel", "Violet Steel"),
        ):
            self.assertIn(f'"{key}"', source)
            self.assertIn(f'"label": "{label}"', source)
            self.assertIn('"preview_bg"', source)


if __name__ == "__main__":
    unittest.main()
